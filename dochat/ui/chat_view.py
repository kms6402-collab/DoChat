"""스크롤 가능한 메시지 버블 리스트 + 드래그앤드롭 파일 전송."""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dochat import config
from dochat.models.message import ConversationType, Message, MessageType
from dochat.ui.message_bubble import MessageBubble

# 팀즈 스타일 그룹핑: 같은 발신자의 메시지가 이 시간(초) 안에 연달아 오면
# 아바타/이름/시각 헤더를 생략하고 이어붙여 보여준다.
GROUP_HEADER_GAP_SEC = 300


class ChatView(QWidget):
    """현재 대화의 메시지들을 세로로 나열해 보여주는 스크롤 영역."""

    file_dropped = Signal(str)  # 드롭된 파일의 로컬 경로

    def __init__(self, chat_engine, storage, parent: QWidget | None = None):
        super().__init__(parent)
        self._chat_engine = chat_engine
        self._storage = storage

        self.conversation_id: str | None = None
        self.conversation_type: str | None = None
        self.my_id: str | None = None

        self._bubbles_by_file_id: dict[str, MessageBubble] = {}
        self._bubbles_by_message_id: dict[str, MessageBubble] = {}
        self._bubbles: list[MessageBubble] = []
        self._contact_name_cache: dict[str, str] = {}

        # 팀즈 스타일 연속 메시지 그룹핑 상태 (대화 전환/clear 시 리셋됨)
        self._last_sender_id: str | None = None
        self._last_ts: float | None = None

        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("ChatScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll_area)

        self._viewport = QWidget()
        self._viewport.setObjectName("ChatViewport")
        self._viewport_layout = QVBoxLayout(self._viewport)
        self._viewport_layout.setContentsMargins(8, 12, 8, 12)
        self._viewport_layout.setSpacing(2)
        self._viewport_layout.addStretch(1)

        self._empty_label = QLabel("대화를 선택해 주세요.")
        self._empty_label.setObjectName("EmptyStateLabel")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._viewport_layout.insertWidget(0, self._empty_label)

        self._scroll_area.setWidget(self._viewport)

        # 실제로 드롭을 받는 위젯은 화면에 보이는 QScrollArea 내부 viewport()이지
        # ChatView 자신이 아니다(스크롤 영역이 ChatView 전체를 덮고 있으므로).
        # ChatView의 dragEnterEvent/dropEvent만 구현해 두면 이 안쪽 viewport가
        # 먼저 이벤트를 받아 파일을 끌어다 놓아도 반응이 없었다 - 이벤트 필터로
        # 안쪽 viewport의 드래그&드롭 이벤트를 그대로 ChatView 처리 로직에 넘긴다.
        self._scroll_area.viewport().setAcceptDrops(True)
        self._scroll_area.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802 (Qt 오버라이드 메서드명)
        if watched is self._scroll_area.viewport():
            if event.type() == QEvent.DragEnter:
                self.dragEnterEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.DragMove:
                self.dragMoveEvent(event)
                return event.isAccepted()
            if event.type() == QEvent.Drop:
                self.dropEvent(event)
                return True
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------
    def _clear_bubbles(self) -> None:
        """추가된 메시지 버블만 제거한다 (``_empty_label``/stretch는 건드리지 않음)."""
        self._bubbles_by_file_id.clear()
        self._bubbles_by_message_id.clear()
        for bubble in self._bubbles:
            self._viewport_layout.removeWidget(bubble)
            bubble.setParent(None)
            bubble.deleteLater()
        self._bubbles.clear()
        self._last_sender_id = None
        self._last_ts = None

    def _resolve_sender_name(self, sender_id: str) -> str:
        if not sender_id:
            return "상대방"
        if sender_id == self.my_id:
            return "나"
        if sender_id in self._contact_name_cache:
            return self._contact_name_cache[sender_id]
        contact = self._chat_engine.get_contact_for_sender(sender_id)
        name = contact.nickname if contact else sender_id
        self._contact_name_cache[sender_id] = name
        return name

    def _resolve_sender_avatar_path(self, sender_id: str) -> str | None:
        """발신자의 프로필 사진 캐시 경로를 돌려준다(없으면 None -> AvatarWidget이
        이니셜로 폴백한다). 아바타는 로컬 Contact.id로 캐시되는데, 이는 메시지의
        sender_id(상대의 전역 CLIENT_ID)와 다른 경우가 많으므로(_resolve_sender_name
        과 동일한 이유) 반드시 get_contact_for_sender()로 로컬 id를 거쳐야 한다."""
        if not sender_id:
            return None
        if sender_id == self.my_id:
            return str(config.MY_AVATAR_PATH) if config.MY_AVATAR_PATH.exists() else None
        contact = self._chat_engine.get_contact_for_sender(sender_id)
        if contact is None:
            return None
        return str(config.AVATAR_DIR / f"{contact.id}.jpg")

    def _make_bubble(self, message: Message) -> MessageBubble:
        is_mine = message.sender_id == self.my_id
        sender_name = self._resolve_sender_name(message.sender_id)
        sender_avatar_path = self._resolve_sender_avatar_path(message.sender_id)

        if message.type == MessageType.SYSTEM:
            show_header = False
            # 시스템 메시지(입장/퇴장) 다음에 오는 실제 메시지는 항상 헤더를
            # 새로 보여주는 게 자연스러우므로 그룹핑 상태를 리셋한다.
            self._last_sender_id = None
            self._last_ts = None
        else:
            show_header = (
                message.sender_id != self._last_sender_id
                or self._last_ts is None
                or message.timestamp - self._last_ts > GROUP_HEADER_GAP_SEC
            )
            self._last_sender_id = message.sender_id
            self._last_ts = message.timestamp

        file_record = None
        resumable = False
        if message.type == MessageType.FILE and message.file_id:
            file_record = self._storage.get_file_record(message.file_id)
            resumable = self._storage.get_resumable_download(message.file_id) is not None

        bubble = MessageBubble(
            message=message,
            is_mine=is_mine,
            sender_name=sender_name,
            sender_avatar_path=sender_avatar_path,
            show_header=show_header,
            file_record=file_record,
            storage=self._storage,
            on_cancel_requested=self._on_cancel_requested,
            on_resume_requested=self._on_resume_requested,
            resumable=resumable,
            on_delete_requested=self._on_delete_requested,
            on_edit_requested=self._on_edit_requested,
        )
        if message.file_id:
            self._bubbles_by_file_id[message.file_id] = bubble
        if message.id:
            self._bubbles_by_message_id[message.id] = bubble
        return bubble

    def _append_bubble_widget(self, bubble: MessageBubble) -> None:
        insert_index = self._viewport_layout.count() - 1  # stretch 앞에 삽입
        self._viewport_layout.insertWidget(insert_index, bubble)
        self._bubbles.append(bubble)

    def _scroll_to_bottom(self) -> None:
        def _do_scroll():
            bar = self._scroll_area.verticalScrollBar()
            bar.setValue(bar.maximum())

        # 새 버블이 추가된 직후에는 스크롤 영역의 range(maximum)가 아직 레이아웃
        # 갱신 전이라 한 번만 시도하면 끝까지 못 내려가는 경우가 있었다. 즉시
        # 한 번 시도하고, 레이아웃이 마무리된 다음 프레임에서 다시 한 번
        # 시도해 항상 맨 아래로 내려가도록 한다.
        _do_scroll()
        QTimer.singleShot(0, _do_scroll)

    # ------------------------------------------------------------------
    def clear(self) -> None:
        """선택된 대화가 없는 초기 상태로 되돌린다 (예: 대화 상대 삭제 시)."""
        self.conversation_id = None
        self.conversation_type = None
        self._clear_bubbles()
        self._empty_label.setText("대화를 선택해 주세요.")
        self._empty_label.show()

    def set_conversation(self, conversation_id: str, conversation_type: str, my_id: str) -> None:
        """대화 전환: 기존 버블을 지우고 히스토리를 새로 로드한다."""
        self.conversation_id = conversation_id
        self.conversation_type = conversation_type
        self.my_id = my_id

        self._clear_bubbles()
        self._empty_label.hide()

        messages = self._chat_engine.get_conversation_messages(conversation_id)
        if not messages:
            self._empty_label.setText("아직 대화 내용이 없습니다. 메시지를 보내보세요.")
            self._empty_label.show()
        for message in messages:
            bubble = self._make_bubble(message)
            self._append_bubble_widget(bubble)

        self._scroll_to_bottom()

        # 대화를 열 때마다 상대에게 읽음 확인을 보낸다.
        self._chat_engine.mark_conversation_read(conversation_id, conversation_type)

    def append_message(self, message: Message) -> None:
        """새 메시지 하나를 리스트 끝에 추가하고 자동 스크롤한다."""
        if self.conversation_id is None or message.conversation_id != self.conversation_id:
            return
        self._empty_label.hide()
        bubble = self._make_bubble(message)
        self._append_bubble_widget(bubble)
        self._scroll_to_bottom()

    def ensure_file_bubble(self, file_id: str) -> None:
        """file_progress가 도착했는데 아직 버블이 없다면(수신 시작/전송 시작 시점)
        FileRecord를 근거로 임시 버블을 즉석에서 만들어 보여준다.
        완료 시점에 set_conversation()으로 다시 로드되면 storage의 실제
        Message로 교체된다."""
        if file_id in self._bubbles_by_file_id or self.conversation_id is None:
            return
        record = self._storage.get_file_record(file_id)
        if record is None or record.conversation_id != self.conversation_id:
            return

        if record.direction == "out":
            sender_id = self.my_id or ""
        elif self.conversation_type == ConversationType.DIRECT:
            sender_id = self.conversation_id
        else:
            sender_id = ""  # 그룹 수신 파일은 완료 전까지 발신자를 알 수 없음

        temp_message = Message(
            id=f"__pending__{file_id}",
            conversation_id=self.conversation_id,
            conversation_type=self.conversation_type,
            sender_id=sender_id,
            type=MessageType.FILE,
            timestamp=record.timestamp,
            file_id=file_id,
        )
        self._empty_label.hide()
        bubble = self._make_bubble(temp_message)
        self._append_bubble_widget(bubble)
        self._scroll_to_bottom()

    def update_file_progress(self, file_id: str, done: int, total: int) -> None:
        """해당 file_id의 버블을 찾아 진행률을 갱신한다."""
        bubble = self._bubbles_by_file_id.get(file_id)
        if bubble is not None:
            bubble.update_progress(done, total)

    def mark_file_completed(self, file_id: str, success: bool) -> None:
        bubble = self._bubbles_by_file_id.get(file_id)
        if bubble is not None:
            bubble.mark_completed(success)

    def mark_file_cancelled(self, file_id: str) -> None:
        """해당 file_id의 버블을 찾아 취소 상태로 갱신한다."""
        bubble = self._bubbles_by_file_id.get(file_id)
        if bubble is not None:
            resumable = self._storage.get_resumable_download(file_id) is not None
            bubble.mark_cancelled(resumable=resumable)

    def _on_cancel_requested(self, file_id: str, direction: str) -> None:
        if direction == "out":
            self._chat_engine.cancel_outgoing_file(file_id)
        elif direction == "in":
            self._chat_engine.cancel_incoming_file(file_id)

    def _on_resume_requested(self, file_id: str) -> None:
        self._chat_engine.resume_incoming_file(file_id)

    def _on_delete_requested(self, message_id: str) -> None:
        self._chat_engine.delete_message(message_id, self.conversation_id, self.conversation_type)

    def _on_edit_requested(self, message_id: str, new_text: str) -> None:
        self._chat_engine.edit_message(
            message_id, self.conversation_id, self.conversation_type, new_text
        )

    def mark_message_deleted(self, message_id: str) -> None:
        """message_deleted 시그널 수신 시 해당 버블을 즉시 "삭제된 메시지입니다"로 갱신한다."""
        bubble = self._bubbles_by_message_id.get(message_id)
        if bubble is not None:
            bubble.mark_deleted()

    def mark_message_edited(self, message_id: str, new_text: str) -> None:
        """message_edited 시그널 수신 시 해당 버블의 텍스트를 새 내용으로 갱신한다."""
        bubble = self._bubbles_by_message_id.get(message_id)
        if bubble is not None:
            bubble.update_text(new_text)

    def mark_messages_read_up_to(self, conversation_id: str, up_to_ts: float) -> None:
        """읽음 확인(READ_RECEIPT)이 도착했을 때, 현재 표시 중인 대화면 해당
        시각 이전에 내가 보낸 메시지 버블들에 '읽음' 표시를 갱신한다."""
        if self.conversation_id != conversation_id:
            return
        now = time.time()
        for bubble in list(self._bubbles_by_message_id.values()):
            message = bubble.message
            if (
                message.sender_id == self.my_id
                and message.timestamp <= up_to_ts
                and message.read_at is None
            ):
                message.read_at = now
                bubble.update_read_status(now)

    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        for url in urls:
            local_path = url.toLocalFile()
            if local_path:
                self.file_dropped.emit(local_path)
        event.acceptProposedAction()
