"""하단 메시지 입력 영역: 텍스트 입력 + 파일첨부 + 전송."""
from __future__ import annotations

import tempfile
import uuid
from html.parser import HTMLParser
from pathlib import Path

from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QImage, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QWidget,
)


class _TableTextExtractor(HTMLParser):
    """HTML 표(<table>)를 한 줄짜리 텍스트로 변환하기 위한 간단한 파서."""

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._current_cell is not None:
            if self._current_row is not None:
                self._current_row.append("".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self._rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def to_text(self) -> str:
        row_texts = [" | ".join(cells) for cells in self._rows if cells]
        return " / ".join(row_texts)


class ComposeBar(QWidget):
    """텍스트 전송과 파일 선택을 담당하는 하단 바."""

    text_submitted = Signal(str)
    file_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ComposeBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self._attach_button = QPushButton("\U0001F4CE")  # 📎
        self._attach_button.setObjectName("AttachButton")
        self._attach_button.setToolTip("파일 첨부")
        self._attach_button.setFixedSize(34, 34)
        self._attach_button.clicked.connect(self._on_attach_clicked)

        self._input = QLineEdit()
        self._input.setObjectName("ComposeInput")
        self._input.setPlaceholderText("메시지를 입력하세요...")
        self._input.returnPressed.connect(self._on_submit)
        self._input.installEventFilter(self)

        self._send_button = QPushButton("전송")
        self._send_button.setObjectName("SendButton")
        self._send_button.clicked.connect(self._on_submit)

        layout.addWidget(self._attach_button)
        layout.addWidget(self._input, 1)
        layout.addWidget(self._send_button)

        self.setEnabled(False)  # 대화를 선택하기 전엔 비활성화

    # ------------------------------------------------------------------
    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self.text_submitted.emit(text)
        self._input.clear()

    def _on_attach_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "전송할 파일 선택")
        if path:
            self.file_selected.emit(path)

    def clear_input(self) -> None:
        self._input.clear()

    def set_active(self, active: bool) -> None:
        """대화가 선택되어 입력 가능한 상태인지 설정."""
        self.setEnabled(active)
        if active:
            self._input.setFocus()

    # ------------------------------------------------------------------
    # 클립보드 붙여넣기 형식 선택
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 (Qt 오버라이드 메서드명)
        if (
            obj is self._input
            and event.type() == QEvent.KeyPress
            and event.matches(QKeySequence.Paste)
        ):
            self._handle_paste()
            return True
        return super().eventFilter(obj, event)

    def _handle_paste(self) -> None:
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()

        has_image = mime.hasImage()
        has_html = mime.hasHtml()
        has_text = mime.hasText()

        available: list[str] = []
        if has_image:
            available.append("image")
        if has_html and self._looks_like_table(mime.html()):
            available.append("table")
        if has_text:
            available.append("text")

        if len(available) <= 1:
            # 형식이 하나뿐이면 고민할 필요 없이 바로 처리
            if available:
                self._apply_paste_format(available[0], mime)
            return

        self._show_paste_choice_popup(available, mime)

    @staticmethod
    def _looks_like_table(html: str) -> bool:
        return "<table" in html.lower()

    def _show_paste_choice_popup(self, available: list[str], mime) -> None:
        menu = QMenu(self)
        labels = {
            "image": "\U0001F5BC 사진으로 붙여넣기",  # 🖼 사진으로 붙여넣기
            "table": "\U0001F4CB 표 형식 그대로 붙여넣기",  # 📋 표 형식 그대로 붙여넣기
            "text": "\U0001F4DD 텍스트로 붙여넣기",  # 📝 텍스트로 붙여넣기
        }
        actions = {}
        for kind in available:
            action = menu.addAction(labels.get(kind, kind))
            actions[action] = kind
        pos = self._input.mapToGlobal(self._input.rect().topRight())
        chosen = menu.exec(pos)
        if chosen is not None:
            self._apply_paste_format(actions[chosen], mime)

    def _apply_paste_format(self, kind: str, mime) -> None:
        if kind == "image":
            image = mime.imageData()
            if isinstance(image, QImage) and not image.isNull():
                temp_path = Path(tempfile.gettempdir()) / f"dochat_paste_{uuid.uuid4().hex}.png"
                if image.save(str(temp_path), "PNG"):
                    self.file_selected.emit(str(temp_path))
        elif kind == "table":
            extractor = _TableTextExtractor()
            extractor.feed(mime.html())
            text = extractor.to_text()
            if text:
                self._input.insert(text)
        elif kind == "text":
            text = mime.text()
            if text:
                self._input.insert(text)
