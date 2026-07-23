"""한 개의 채팅 메시지(텍스트/파일)를 표시하는 말풍선 위젯."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dochat.models.message import FileRecord, FileStatus, MessageType
from dochat.models.message import Message

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
MAX_THUMB = 200


def _human_size(size: int) -> str:
    n = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


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
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._message = message
        self._is_mine = is_mine
        self._file_record = file_record
        self._progress_bar: QProgressBar | None = None
        self._read_label: QLabel | None = None

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
        bubble_layout = QVBoxLayout(bubble_frame)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(6)

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
                layout.addWidget(image_label)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        if not is_image:
            icon_label = QLabel("\U0001F4C4")  # 📄
            icon_label.setStyleSheet("background: transparent; font-size: 18px;")
            name_row.addWidget(icon_label)
        name_label = QLabel(filename)
        name_label.setObjectName("FileNameLabel")
        name_label.setStyleSheet(
            "color: #FFFFFF;" if self._is_mine else "color: #2C2F36;"
        )
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
        else:
            self._progress_bar = None

    def _open_file(self) -> None:
        if self._message.type != MessageType.FILE:
            return
        if not self._file_record:
            return
        path = self._file_record.local_path
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

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
        """파일 전송/수신 진행률 갱신 (0%~100%). 완료 시 바를 숨긴다."""
        if self._progress_bar is None:
            return
        pct = 0 if total <= 0 else int(done * 100 / total)
        self._progress_bar.setValue(min(100, max(0, pct)))

    def mark_completed(self, success: bool = True) -> None:
        """전송/수신 완료 시 진행률 바를 숨긴다."""
        if self._progress_bar is not None:
            self._progress_bar.hide()
        if success and self._file_record is not None:
            self._file_record.status = FileStatus.COMPLETED
