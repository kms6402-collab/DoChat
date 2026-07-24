"""IP:포트를 입력해 DoChat 연결 가능 여부/지연시간을 확인하는 진단 다이얼로그."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dochat.config import DEFAULT_LISTEN_PORT


class NetworkDiagnosticDialog(QDialog):
    """상대방 IP:포트로 연결(ping) 가능 여부와 응답 시간을 확인한다."""

    def __init__(self, chat_engine, parent: QWidget | None = None):
        super().__init__(parent)
        self._chat_engine = chat_engine
        self.setWindowTitle("네트워크 연결 진단")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._ip_edit = QLineEdit()
        self._ip_edit.setPlaceholderText("예: 192.168.0.10")
        form.addRow("상대 IP", self._ip_edit)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(DEFAULT_LISTEN_PORT)
        form.addRow("포트", self._port_spin)

        self._test_button = QPushButton("연결 테스트")
        self._test_button.clicked.connect(self._on_test_clicked)
        layout.addWidget(self._test_button)

        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        layout.addWidget(self._result_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _on_test_clicked(self) -> None:
        ip = self._ip_edit.text().strip()
        port = self._port_spin.value()
        if not ip:
            self._result_label.setText("IP를 입력해 주세요.")
            return
        self._test_button.setEnabled(False)
        self._result_label.setText("확인 중...")

        def on_result(result: dict) -> None:
            self._test_button.setEnabled(True)
            if result.get("reachable"):
                latency = result.get("latency_ms") or 0.0
                self._result_label.setText(f"✅ 연결 가능 (응답 시간: {latency:.0f}ms)")
            else:
                error = result.get("error") or "알 수 없는 오류"
                self._result_label.setText(f"❌ 연결 실패: {error}")

        self._chat_engine.ping_address(ip, port, on_result)
