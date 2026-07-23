"""스크롤 가능한 메시지 버블 리스트 + 드래그앤드롭 파일 전송."""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dochat.models.message import ConversationType, Message, MessageType
from dochat.ui.message_bubble import MessageBubble


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

    def _resolve_sender_name(self, sender_id: str) -> str:
        if not sender_id:
            return "상대방"
        if sender_id == self.my_id:
            return "나"
        if sender_id in self._contact_name_cache:
            return self._contact_name_cache[sender_id]
        contact = self._chat_engine.get_contact(sender_id)
        name = contact.nickname if contact else sender_id
        self._contact_name_cache[sender_id] = name
        return name

    def _make_bubble(self, message: Message) -> MessageBubble:
        is_mine = message.sender_id == self.my_id
        show_sender = self.conversation_type == ConversationType.GROUP
        sender_name = self._resolve_sender_name(message.sender_id) if show_sender else ""

        file_record = None
        if message.type == MessageType.FILE and message.file_id:
            file_record = self._storage.get_file_record(message.file_id)

        bubble = MessageBubble(
            message=message,
            is_mine=is_mine,
            sender_name=sender_name,
            show_sender=show_sender,
            file_record=file_record,
            on_cancel_requested=self._on_cancel_requested,
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
            bubble.mark_cancelled()

    def _on_cancel_requested(self, file_id: str, direction: str) -> None:
        if direction == "out":
            self._chat_engine.cancel_outgoing_file(file_id)
        elif direction == "in":
            self._chat_engine.cancel_incoming_file(file_id)

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
