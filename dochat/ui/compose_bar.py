"""하단 메시지 입력 영역: 텍스트 입력 + 파일첨부 + 전송."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)


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
