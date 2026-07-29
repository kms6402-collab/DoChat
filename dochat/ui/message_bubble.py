"""한 개의 채팅 메시지(텍스트/파일)를 표시하는 말풍선 위젯."""
from __future__ import annotations

import os
import time
from typing import Callable

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dochat.config import FILE_CHUNK_SIZE
from dochat.models.message import FileRecord, FileStatus, MessageType
from dochat.models.message import Message
from dochat.ui.avatar_widget import AvatarWidget, ME_AVATAR_COLOR, avatar_color_for
from dochat.ui.themes import DEFAULT_FONT_SIZE, get_app_theme

try:
    # 같은 앱 내부 재사용: 폴더에서 보기(OS별 파일 탐색기 열기) 로직을 file_room과 공유한다.
    from dochat.ui.file_room import _reveal_in_file_manager
except ImportError:  # pragma: no cover - 순환참조 등 예외 상황에 대한 안전장치
    _reveal_in_file_manager = None

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
MAX_THUMB = 200

# 팀즈 스타일 헤더(아바타+이름+시각) 관련 상수.
HEADER_AVATAR_SIZE = 36
HEADER_ROW_SPACING = 8
# show_header=False일 때 내용물을 아바타 컬럼 아래로 정렬시키는 들여쓰기 폭.
CONTENT_INDENT = HEADER_AVATAR_SIZE + HEADER_ROW_SPACING


def _human_size(size: int) -> str:
    n = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _human_speed(bytes_per_sec: float) -> str:
    """바이트/초 값을 "1.2 MB/s" 같은 사람이 읽기 좋은 형식으로 변환한다."""
    return f"{_human_size(int(max(0, bytes_per_sec)))}/s"


def _human_eta(seconds: float) -> str:
    """남은 초를 "약 12초 남음" 같은 형식으로 변환한다."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"약 {seconds}초 남음"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"약 {minutes}분 {sec}초 남음"
    hours, minutes = divmod(minutes, 60)
    return f"약 {hours}시간 {minutes}분 남음"


def _format_speed_and_eta(
    history: list[tuple[float, int]], total: int, chunk_size: int = FILE_CHUNK_SIZE
) -> str:
    """진행률 히스토리(시각, done_chunks)로부터 "속도 · 남은시간" 문자열을 만든다.

    히스토리가 2개 미만이거나 유효한 속도를 계산할 수 없으면 빈 문자열을 반환한다.
    순수 함수로 분리해 위젯 없이도 단위 테스트하듯 검증할 수 있게 했다.
    """
    if len(history) < 2 or total <= 0:
        return ""

    oldest_t, oldest_done = history[0]
    newest_t, newest_done = history[-1]
    dt = newest_t - oldest_t
    dchunks = newest_done - oldest_done
    if dt <= 0 or dchunks <= 0:
        return ""

    chunks_per_sec = dchunks / dt
    bytes_per_sec = chunks_per_sec * chunk_size
    speed_text = _human_speed(bytes_per_sec)

    remaining_chunks = max(0, total - newest_done)
    remaining_sec = remaining_chunks / chunks_per_sec
    eta_text = _human_eta(remaining_sec)
    return f"{speed_text} · {eta_text}"


class _ClickableFrame(QFrame):
    """더블클릭 시 콜백을 호출하는 프레임."""

    def __init__(self, on_double_click=None, parent=None):
        super().__init__(parent)
        self._on_double_click = on_double_click

    def mouseDoubleClickEvent(self, event):
        if self._on_double_click:
            self._on_double_click()
        super().mouseDoubleClickEvent(event)


class MessageBubble(QWidget):
    """단일 메시지 버블. 텍스트/파일(이미지 썸네일 또는 문서) 렌더링을 담당."""

    def __init__(
        self,
        message: Message,
        is_mine: bool,
        sender_name: str = "",
        sender_avatar_path: str | None = None,
        show_header: bool = False,
        file_record: FileRecord | None = None,
        on_cancel_requested: Callable[[str, str], None] | None = None,
        on_resume_requested: Callable[[str], None] | None = None,
        resumable: bool = False,
        parent: QWidget | None = None,
        storage=None,
        on_delete_requested: Callable[[str], None] | None = None,
        on_edit_requested: Callable[[str, str], None] | None = None,
    ):
        super().__init__(parent)
        self._message = message
        self._is_mine = is_mine
        self._file_record = file_record
        self._on_cancel_requested = on_cancel_requested
        self._on_resume_requested = on_resume_requested
        self._resumable = resumable
        self._progress_bar: QProgressBar | None = None
        self._cancel_button: QPushButton | None = None
        self._file_action_row: QHBoxLayout | None = None
        self._cancelled_label: QLabel | None = None
        self._resume_button: QPushButton | None = None
        self._read_label: QLabel | None = None
        self._on_delete_requested = on_delete_requested
        self._on_edit_requested = on_edit_requested
        self._text_label: QLabel | None = None
        self._edited_label: QLabel | None = None
        self._bubble_frame: QFrame | None = None
        self._bubble_layout: QVBoxLayout | None = None
        self._speed_label: QLabel | None = None
        self._progress_history: list[tuple[float, int]] = []

        # 채팅 테마 반영: 정적 QSS의 objectName 규칙 대신 실행 중 계산된 색상을
        # 인라인 스타일시트로 적용해 즉시 반영되도록 한다.
        # 참고: 레퍼런스(팀즈 스타일) 디자인에서는 내 메시지/상대 메시지 모두 카드
        # 배경 없이 완전히 동일한 평면(flat) 처리를 하므로, 더 이상 "내 말풍선
        # 틴트 색"을 계산할 필요가 없다(과거엔 bubble_mine_color 커스텀 설정이나
        # theme.selection_bg를 카드 배경으로 썼었다).
        app_theme = get_app_theme(storage)
        self._text_color = app_theme.text_primary
        self._text_secondary = app_theme.text_secondary
        # 앱 전체 폰트 크기 설정을 그대로 따라 메시지 영역의 모든 텍스트가
        # 동일한 크기를 쓰도록 한다(파일/이모지 아이콘 글리프 크기는 예외).
        saved_font_size = storage.get_setting("app_font_size") if storage else None
        self._font_size = int(saved_font_size) if saved_font_size else int(DEFAULT_FONT_SIZE)

        if message.type == MessageType.SYSTEM:
            self._build_system_content()
            return

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 2, 12, 2)
        outer.setSpacing(2)

        if show_header:
            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(HEADER_ROW_SPACING)

            avatar_color = (
                ME_AVATAR_COLOR if is_mine else avatar_color_for(self._message.sender_id)
            )
            avatar = AvatarWidget(
                size=HEADER_AVATAR_SIZE,
                initial=sender_name or "?",
                bg_color=avatar_color,
                photo_path=sender_avatar_path,
            )
            header_row.addWidget(avatar)

            name_label = QLabel(sender_name)
            name_label.setObjectName("BubbleSender")
            name_label.setStyleSheet(
                f"color: {self._text_color}; font-weight: 600; background: transparent;"
            )
            header_row.addWidget(name_label)

            time_label = QLabel(self._format_time(message.timestamp))
            time_label.setStyleSheet(
                f"color: {self._text_secondary}; font-size: {self._font_size}px; background: transparent;"
            )
            header_row.addWidget(time_label)

            header_row.addStretch(1)
            outer.addLayout(header_row)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)
        if not show_header:
            spacer = QWidget()
            spacer.setFixedWidth(CONTENT_INDENT)
            content_row.addWidget(spacer)

        bubble_frame = _ClickableFrame(on_double_click=self._open_file)
        # 레퍼런스 디자인: 내 메시지/상대 메시지 모두 카드 배경/테두리 없이 완전히
        # 동일한 평면 처리를 한다(아바타 색과 발신자 이름만으로 구분).
        bubble_frame.setObjectName("BubbleFrameMine" if is_mine else "BubbleFrameOther")
        bubble_frame.setStyleSheet("background: transparent;")
        bubble_layout = QVBoxLayout(bubble_frame)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(6)
        self._bubble_layout = bubble_layout
        self._bubble_frame = bubble_frame

        if message.type == MessageType.FILE:
            self._build_file_content(bubble_layout)
        else:
            self._build_text_content(bubble_layout)

        if is_mine and message.type == MessageType.TEXT and not message.deleted:
            bubble_frame.setContextMenuPolicy(Qt.CustomContextMenu)
            bubble_frame.customContextMenuRequested.connect(self._on_bubble_context_menu)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(4)

        if is_mine and message.type == MessageType.TEXT:
            self._read_label = QLabel("읽음")
            self._read_label.setObjectName("BubbleReadStatus")
            self._read_label.setStyleSheet(
                f"color: {self._text_secondary}; font-size: {self._font_size}px; background: transparent;"
            )
            self._read_label.setVisible(bool(message.read_at))
            meta_row.addWidget(self._read_label)

        if not show_header:
            meta_label = QLabel(self._format_time(message.timestamp))
            meta_label.setObjectName("BubbleMetaMine" if is_mine else "BubbleMeta")
            meta_label.setStyleSheet(
                f"color: {self._text_secondary}; font-size: {self._font_size}px; background: transparent;"
            )
            meta_row.addWidget(meta_label)

        # meta_row는 내용이 비어 있어도(둘 다 조건 미충족) 항상 bubble_layout의
        # 마지막 항목으로 추가한다: update_text/mark_completed/mark_cancelled가
        # "bubble_layout.count() - 1" 위치(=meta_row 바로 앞)에 새 행을 끼워 넣는
        # 방식으로 동작하므로, meta_row가 항상 마지막에 있어야 그 위치 가정이
        # 상대방 메시지(is_mine=False)에서도 깨지지 않는다.
        meta_row.addStretch(1)
        bubble_layout.addLayout(meta_row)

        bubble_frame.setMaximumWidth(720)
        bubble_frame.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)

        content_row.addWidget(bubble_frame)
        content_row.addStretch(1)
        outer.addLayout(content_row)

    # ------------------------------------------------------------------
    @staticmethod
    def _format_time(ts: float) -> str:
        return time.strftime("%H:%M", time.localtime(ts))

    def _build_text_content(self, layout: QVBoxLayout) -> None:
        text_color = self._text_color
        if self._message.deleted:
            text_label = QLabel("삭제된 메시지입니다")
            text_label.setStyleSheet(
                f"color: {text_color}; background: transparent; font-style: italic;"
            )
        else:
            text_label = QLabel(self._message.text or "")
            text_label.setStyleSheet(f"color: {text_color}; background: transparent;")
        text_label.setObjectName("BubbleTextMine" if self._is_mine else "BubbleTextOther")
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(text_label)
        self._text_label = text_label

        if self._message.edited_at and not self._message.deleted:
            edited_label = QLabel("(수정됨)")
            edited_label.setStyleSheet(
                f"color: {text_color}; background: transparent; font-size: {self._font_size}px;"
            )
            layout.addWidget(edited_label)
            self._edited_label = edited_label

    def _build_system_content(self) -> None:
        """그룹 시스템 메시지(입장/퇴장 등 알림)를 카카오톡/슬랙 스타일의
        가운데 정렬된 작은 회색 알약(pill) 라벨로 표시한다."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 4, 12, 4)
        outer.setSpacing(0)

        label = QLabel(self._message.text or "")
        label.setObjectName("SystemMessageLabel")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet(
            "background-color: rgba(128, 128, 128, 0.18);"
            " color: #8A8F98;"
            f" font-size: {self._font_size}px;"
            " padding: 4px 12px;"
            " border-radius: 10px;"
        )
        outer.addWidget(label, alignment=Qt.AlignCenter)

    def _build_file_content(self, layout: QVBoxLayout) -> None:
        record = self._file_record
        filename = record.filename if record else "파일"
        size = record.size if record else 0
        local_path = record.local_path if record else ""
        status = record.status if record else FileStatus.SENDING

        ext = os.path.splitext(filename)[1].lower()
        is_image = ext in IMAGE_EXTS and local_path and os.path.exists(local_path)

        if is_image:
            pixmap = QPixmap(local_path)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    MAX_THUMB,
                    MAX_THUMB,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                image_label = QLabel()
                image_label.setPixmap(pixmap)
                image_label.setCursor(Qt.PointingHandCursor)
                image_label.mousePressEvent = lambda event: self._open_lightbox()
                layout.addWidget(image_label)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        if not is_image:
            icon_label = QLabel("\U0001F4C4")  # 📄
            icon_label.setStyleSheet("background: transparent; font-size: 18px;")
            name_row.addWidget(icon_label)
        name_label = QLabel(filename)
        name_label.setObjectName("FileNameLabel")
        name_label.setStyleSheet(f"color: {self._text_color};")
        name_label.setWordWrap(True)
        name_row.addWidget(name_label, 1)
        layout.addLayout(name_row)

        meta_label = QLabel(_human_size(size))
        meta_label.setObjectName("FileMetaLabel")
        meta_label.setStyleSheet(
            f"color: {self._text_secondary}; font-size: {self._font_size}px; background: transparent;"
        )
        layout.addWidget(meta_label)

        if status in (FileStatus.SENDING, FileStatus.RECEIVING):
            bar = QProgressBar()
            bar.setObjectName("FileProgressOther" if not self._is_mine else "")
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            layout.addWidget(bar)
            self._progress_bar = bar

            speed_label = QLabel("")
            speed_label.setStyleSheet(f"font-size: {self._font_size}px; color: #9AA1AC; background: transparent;")
            layout.addWidget(speed_label)
            self._speed_label = speed_label

            cancel_row = QHBoxLayout()
            cancel_row.setContentsMargins(0, 0, 0, 0)
            cancel_row.addStretch(1)
            cancel_button = QPushButton("취소")
            cancel_button.setCursor(Qt.PointingHandCursor)
            cancel_button.clicked.connect(self._on_cancel_clicked)
            cancel_row.addWidget(cancel_button)
            layout.addLayout(cancel_row)
            self._cancel_button = cancel_button
        elif status == FileStatus.CANCELLED:
            self._progress_bar = None
            cancelled_row = QHBoxLayout()
            cancelled_row.setContentsMargins(0, 0, 0, 0)
            cancelled_row.setSpacing(6)
            cancelled_label = QLabel("취소됨")
            cancelled_label.setStyleSheet(f"color: #9AA1AC; font-size: {self._font_size}px; background: transparent;")
            cancelled_row.addWidget(cancelled_label)
            if self._resumable and record is not None and record.direction == "in":
                resume_button = QPushButton("이어받기")
                resume_button.setCursor(Qt.PointingHandCursor)
                resume_button.clicked.connect(self._on_resume_clicked)
                cancelled_row.addWidget(resume_button)
                self._resume_button = resume_button
            cancelled_row.addStretch(1)
            layout.addLayout(cancelled_row)
            self._cancelled_label = cancelled_label
        elif status == FileStatus.FAILED:
            self._progress_bar = None
            failed_row = QHBoxLayout()
            failed_row.setContentsMargins(0, 0, 0, 0)
            failed_row.setSpacing(6)
            failed_label = QLabel("⚠ 전송 실패")  # ⚠ 전송 실패
            failed_label.setStyleSheet(f"color: #E0433B; font-size: {self._font_size}px; font-weight: 600; background: transparent;")
            failed_row.addWidget(failed_label)
            failed_row.addStretch(1)
            layout.addLayout(failed_row)
        else:
            self._progress_bar = None

        if status == FileStatus.COMPLETED:
            action_row = QHBoxLayout()
            action_row.setContentsMargins(0, 0, 0, 0)
            action_row.setSpacing(6)
            open_button = QPushButton("열기")
            open_button.setCursor(Qt.PointingHandCursor)
            open_button.clicked.connect(self._open_file)
            reveal_button = QPushButton("폴더에서 보기")
            reveal_button.setCursor(Qt.PointingHandCursor)
            reveal_button.clicked.connect(self._reveal_in_folder)
            action_row.addWidget(open_button)
            action_row.addWidget(reveal_button)
            action_row.addStretch(1)
            layout.addLayout(action_row)
            self._file_action_row = action_row

    def _on_bubble_context_menu(self, pos) -> None:
        """내가 보낸 텍스트 메시지 말풍선 우클릭 시 편집/삭제 메뉴를 띄운다."""
        menu = QMenu(self)
        edit_action = menu.addAction("편집")
        delete_action = menu.addAction("삭제")
        chosen = menu.exec(self._bubble_frame.mapToGlobal(pos))
        if chosen == delete_action:
            if self._on_delete_requested is not None:
                self._on_delete_requested(self._message.id)
        elif chosen == edit_action:
            new_text, ok = QInputDialog.getText(
                self, "메시지 편집", "내용:", text=self._message.text or ""
            )
            if ok and new_text.strip() and self._on_edit_requested is not None:
                self._on_edit_requested(self._message.id, new_text)

    def _on_cancel_clicked(self) -> None:
        if self._on_cancel_requested is None or self._file_record is None:
            return
        self._on_cancel_requested(self._file_record.file_id, self._file_record.direction)

    def _on_resume_clicked(self) -> None:
        if self._on_resume_requested is None or self._file_record is None:
            return
        self._on_resume_requested(self._file_record.file_id)

    def _reveal_in_folder(self) -> None:
        if not self._file_record:
            return
        path = self._file_record.local_path
        if not path or not os.path.exists(path):
            return
        if _reveal_in_file_manager is not None:
            _reveal_in_file_manager(path)
        else:  # pragma: no cover - import 실패 시 최소한 폴더는 연다
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _open_file(self) -> None:
        if self._message.type != MessageType.FILE:
            return
        if not self._file_record:
            return
        path = self._file_record.local_path
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_lightbox(self) -> None:
        """이미지 썸네일 단일 클릭 시 확대보기(라이트박스)를 띄운다.

        기존의 더블클릭 시 ``_open_file()``(OS 기본 뷰어로 열기) 동작은 그대로 유지된다.
        """
        if not self._file_record:
            return
        path = self._file_record.local_path
        if not path or not os.path.exists(path):
            return
        from dochat.ui.image_lightbox import ImageLightboxDialog  # 순환참조 방지를 위한 지연 import

        ImageLightboxDialog(path, parent=self).show()

    # ------------------------------------------------------------------
    @property
    def file_id(self) -> str | None:
        return self._message.file_id

    @property
    def message(self) -> Message:
        return self._message

    def update_read_status(self, read_at: float) -> None:
        """상대가 이 메시지를 읽었음을 표시한다 (내가 보낸 텍스트 메시지에만 적용)."""
        self._message.read_at = read_at
        if self._read_label is not None:
            self._read_label.setVisible(True)

    def mark_deleted(self) -> None:
        """이미 렌더링된 텍스트 버블을 즉시 "삭제된 메시지입니다"로 바꾼다(재생성 없이)."""
        self._message.deleted = True
        if self._text_label is not None:
            text_color = self._text_color
            self._text_label.setText("삭제된 메시지입니다")
            self._text_label.setStyleSheet(
                f"color: {text_color}; background: transparent; font-style: italic;"
            )
        if self._edited_label is not None:
            self._edited_label.hide()
        if self._bubble_frame is not None:
            self._bubble_frame.setContextMenuPolicy(Qt.NoContextMenu)

    def update_text(self, new_text: str) -> None:
        """텍스트를 새 내용으로 교체하고 "(수정됨)" 표시를 붙인다."""
        self._message.text = new_text
        self._message.edited_at = time.time()
        if self._text_label is not None:
            self._text_label.setText(new_text)
        if self._edited_label is None and self._bubble_layout is not None:
            text_color = self._text_color
            edited_label = QLabel("(수정됨)")
            edited_label.setStyleSheet(
                f"color: {text_color}; background: transparent; font-size: {self._font_size}px;"
            )
            # meta_row(시간/읽음 표시) 바로 앞에 삽입한다.
            self._bubble_layout.insertWidget(self._bubble_layout.count() - 1, edited_label)
            self._edited_label = edited_label
        elif self._edited_label is not None:
            self._edited_label.show()

    def update_progress(self, done: int, total: int) -> None:
        """파일 전송/수신 진행률 갱신 (0%~100%). 완료 시 바를 숨긴다.

        전송 속도/예상 남은 시간도 함께 갱신한다(백엔드 변경 없이 진행률 콜백이
        오는 시간 간격과 청크 수로 클라이언트에서 직접 추정).
        """
        if self._progress_bar is None:
            return
        pct = 0 if total <= 0 else int(done * 100 / total)
        self._progress_bar.setValue(min(100, max(0, pct)))

        now = time.time()
        self._progress_history.append((now, done))
        self._progress_history = self._progress_history[-10:]

        if self._speed_label is not None:
            self._speed_label.setText(_format_speed_and_eta(self._progress_history, total))

    def mark_completed(self, success: bool = True) -> None:
        """전송/수신 완료 시 진행률 바/취소 버튼을 숨기고, 성공이면 열기/폴더에서 보기
        버튼을 표시한다(대화가 다시 로드되지 않아 버블이 재생성되지 않는 경우 대비)."""
        if self._progress_bar is not None:
            self._progress_bar.hide()
        if self._cancel_button is not None:
            self._cancel_button.hide()
        if self._speed_label is not None:
            self._speed_label.hide()
        if success and self._file_record is not None:
            self._file_record.status = FileStatus.COMPLETED
            if self._file_action_row is None and self._bubble_layout is not None:
                action_row = QHBoxLayout()
                action_row.setContentsMargins(0, 0, 0, 0)
                action_row.setSpacing(6)
                open_button = QPushButton("열기")
                open_button.setCursor(Qt.PointingHandCursor)
                open_button.clicked.connect(self._open_file)
                reveal_button = QPushButton("폴더에서 보기")
                reveal_button.setCursor(Qt.PointingHandCursor)
                reveal_button.clicked.connect(self._reveal_in_folder)
                action_row.addWidget(open_button)
                action_row.addWidget(reveal_button)
                action_row.addStretch(1)
                self._bubble_layout.insertLayout(self._bubble_layout.count() - 1, action_row)
                self._file_action_row = action_row

    def mark_cancelled(self, resumable: bool = False) -> None:
        """전송/수신 취소 시 진행률 바/취소 버튼을 숨기고 "취소됨" 라벨을 표시한다.

        ``resumable=True``이고 수신(direction == "in") 중이던 파일이면 "이어받기"
        버튼도 함께 표시한다(대화가 다시 로드되지 않아 버블이 재생성되지 않는 경우 대비).
        """
        if self._progress_bar is not None:
            self._progress_bar.hide()
        if self._cancel_button is not None:
            self._cancel_button.hide()
        if self._speed_label is not None:
            self._speed_label.hide()
        if self._file_record is not None:
            self._file_record.status = FileStatus.CANCELLED
        self._resumable = resumable or self._resumable
        if self._cancelled_label is None and self._bubble_layout is not None:
            cancelled_row = QHBoxLayout()
            cancelled_row.setContentsMargins(0, 0, 0, 0)
            cancelled_row.setSpacing(6)
            cancelled_label = QLabel("취소됨")
            cancelled_label.setStyleSheet(f"color: #9AA1AC; font-size: {self._font_size}px; background: transparent;")
            cancelled_row.addWidget(cancelled_label)
            if (
                self._resumable
                and self._resume_button is None
                and self._file_record is not None
                and self._file_record.direction == "in"
            ):
                resume_button = QPushButton("이어받기")
                resume_button.setCursor(Qt.PointingHandCursor)
                resume_button.clicked.connect(self._on_resume_clicked)
                cancelled_row.addWidget(resume_button)
                self._resume_button = resume_button
            cancelled_row.addStretch(1)
            self._bubble_layout.insertLayout(self._bubble_layout.count() - 1, cancelled_row)
            self._cancelled_label = cancelled_label
