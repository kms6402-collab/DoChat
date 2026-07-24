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
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dochat.config import FILE_CHUNK_SIZE
from dochat.models.message import FileRecord, FileStatus, MessageType
from dochat.models.message import Message
from dochat.ui.themes import get_theme_colors

try:
    # 같은 앱 내부 재사용: 폴더에서 보기(OS별 파일 탐색기 열기) 로직을 file_room과 공유한다.
    from dochat.ui.file_room import _reveal_in_file_manager
except ImportError:  # pragma: no cover - 순환참조 등 예외 상황에 대한 안전장치
    _reveal_in_file_manager = None

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
MAX_THUMB = 200


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
        show_sender: bool = False,
        file_record: FileRecord | None = None,
        on_cancel_requested: Callable[[str, str], None] | None = None,
        on_resume_requested: Callable[[str], None] | None = None,
        resumable: bool = False,
        parent: QWidget | None = None,
        storage=None,
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
        self._speed_label: QLabel | None = None
        self._progress_history: list[tuple[float, int]] = []

        # 채팅 테마/커스텀 색 반영: 정적 QSS의 objectName 규칙 대신 실행 중
        # 계산된 색상을 인라인 스타일시트로 적용해 즉시 반영되도록 한다.
        self._mine_bg, self._mine_text, self._other_bg, self._other_text = get_theme_colors(storage)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 3, 12, 3)
        outer.setSpacing(0)

        column = QVBoxLayout()
        column.setSpacing(2)

        if show_sender and not is_mine and sender_name:
            sender_label = QLabel(sender_name)
            sender_label.setObjectName("BubbleSender")
            column.addWidget(sender_label)

        bubble_frame = _ClickableFrame(on_double_click=self._open_file)
        bubble_frame.setObjectName("BubbleFrameMine" if is_mine else "BubbleFrameOther")
        bubble_bg = self._mine_bg if is_mine else self._other_bg
        bubble_frame.setStyleSheet(f"background-color: {bubble_bg}; border-radius: 12px;")
        bubble_layout = QVBoxLayout(bubble_frame)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(6)
        self._bubble_layout = bubble_layout

        if message.type == MessageType.FILE:
            self._build_file_content(bubble_layout)
        else:
            self._build_text_content(bubble_layout)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(4)
        if is_mine:
            meta_row.addStretch(1)

        if is_mine and message.type == MessageType.TEXT:
            self._read_label = QLabel("읽음")
            self._read_label.setObjectName("BubbleReadStatus")
            self._read_label.setStyleSheet("color: #C6CDD6; font-size: 10px; background: transparent;")
            self._read_label.setVisible(bool(message.read_at))
            meta_row.addWidget(self._read_label)

        meta_label = QLabel(self._format_time(message.timestamp))
        meta_label.setObjectName("BubbleMetaMine" if is_mine else "BubbleMeta")
        meta_row.addWidget(meta_label)

        if not is_mine:
            meta_row.addStretch(1)

        bubble_layout.addLayout(meta_row)

        bubble_frame.setMaximumWidth(420)
        bubble_frame.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if is_mine:
            row.addStretch(1)
            row.addWidget(bubble_frame)
        else:
            row.addWidget(bubble_frame)
            row.addStretch(1)
        column.addLayout(row)

        outer.addLayout(column)

    # ------------------------------------------------------------------
    @staticmethod
    def _format_time(ts: float) -> str:
        return time.strftime("%H:%M", time.localtime(ts))

    def _build_text_content(self, layout: QVBoxLayout) -> None:
        text_label = QLabel(self._message.text or "")
        text_label.setObjectName("BubbleTextMine" if self._is_mine else "BubbleTextOther")
        text_color = self._mine_text if self._is_mine else self._other_text
        text_label.setStyleSheet(f"color: {text_color}; background: transparent;")
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(text_label)

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
        file_name_color = self._mine_text if self._is_mine else self._other_text
        name_label.setStyleSheet(f"color: {file_name_color};")
        name_label.setWordWrap(True)
        name_row.addWidget(name_label, 1)
        layout.addLayout(name_row)

        meta_label = QLabel(_human_size(size))
        meta_label.setObjectName("FileMetaLabel")
        if self._is_mine:
            meta_label.setStyleSheet("color: #DCE5FA; font-size: 11px; background: transparent;")
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
            speed_label.setStyleSheet("font-size: 10px; color: #9AA1AC; background: transparent;")
            layout.addWidget(speed_label)
            self._speed_label = speed_label

            cancel_row = QHBoxLayout()
            cancel_row.setContentsMargins(0, 0, 0, 0)
            cancel_row.addStretch(1)
            cancel_button = QPushButton("취소")
            cancel_button.setCursor(Qt.PointingHandCursor)
            cancel_button.setFixedHeight(20)
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
            cancelled_label.setStyleSheet("color: #9AA1AC; font-size: 11px; background: transparent;")
            cancelled_row.addWidget(cancelled_label)
            if self._resumable and record is not None and record.direction == "in":
                resume_button = QPushButton("이어받기")
                resume_button.setCursor(Qt.PointingHandCursor)
                resume_button.setFixedHeight(20)
                resume_button.clicked.connect(self._on_resume_clicked)
                cancelled_row.addWidget(resume_button)
                self._resume_button = resume_button
            cancelled_row.addStretch(1)
            layout.addLayout(cancelled_row)
            self._cancelled_label = cancelled_label
        else:
            self._progress_bar = None

        if status == FileStatus.COMPLETED:
            action_row = QHBoxLayout()
            action_row.setContentsMargins(0, 0, 0, 0)
            action_row.setSpacing(6)
            open_button = QPushButton("열기")
            open_button.setCursor(Qt.PointingHandCursor)
            open_button.setFixedHeight(22)
            open_button.clicked.connect(self._open_file)
            reveal_button = QPushButton("폴더에서 보기")
            reveal_button.setCursor(Qt.PointingHandCursor)
            reveal_button.setFixedHeight(22)
            reveal_button.clicked.connect(self._reveal_in_folder)
            action_row.addWidget(open_button)
            action_row.addWidget(reveal_button)
            action_row.addStretch(1)
            layout.addLayout(action_row)
            self._file_action_row = action_row

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
                open_button.setFixedHeight(22)
                open_button.clicked.connect(self._open_file)
                reveal_button = QPushButton("폴더에서 보기")
                reveal_button.setCursor(Qt.PointingHandCursor)
                reveal_button.setFixedHeight(22)
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
            cancelled_label.setStyleSheet("color: #9AA1AC; font-size: 11px; background: transparent;")
            cancelled_row.addWidget(cancelled_label)
            if (
                self._resumable
                and self._resume_button is None
                and self._file_record is not None
                and self._file_record.direction == "in"
            ):
                resume_button = QPushButton("이어받기")
                resume_button.setCursor(Qt.PointingHandCursor)
                resume_button.setFixedHeight(20)
                resume_button.clicked.connect(self._on_resume_clicked)
                cancelled_row.addWidget(resume_button)
                self._resume_button = resume_button
            cancelled_row.addStretch(1)
            self._bubble_layout.insertLayout(self._bubble_layout.count() - 1, cancelled_row)
            self._cancelled_label = cancelled_label
