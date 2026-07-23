"""새 연락처(피어) 추가 다이얼로그."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from dochat.config import DEFAULT_LISTEN_PORT


class AddContactDialog(QDialog):
    """닉네임 / IP / 포트를 입력받는 간단한 다이얼로그."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("새 대화 상대 추가")
        self.setModal(True)
        self.setMinimumWidth(320)

        form = QFormLayout(self)
        form.setSpacing(10)

        self._nickname_edit = QLineEdit()
        self._nickname_edit.setPlaceholderText("예: 김철수")
        form.addRow("닉네임", self._nickname_edit)

        self._ip_edit = QLineEdit()
        self._ip_edit.setPlaceholderText("예: 192.168.0.10")
        form.addRow("IP 주소", self._ip_edit)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(DEFAULT_LISTEN_PORT)
        form.addRow("포트", self._port_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("PrimaryButton")
        buttons.button(QDialogButtonBox.Ok).setText("추가")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._result_values: tuple[str, str, int] | None = None

    def _on_accept(self) -> None:
        nickname = self._nickname_edit.text().strip()
        ip = self._ip_edit.text().strip()
        port = self._port_spin.value()

        if not nickname:
            QMessageBox.warning(self, "입력 오류", "닉네임을 입력해 주세요.")
            return
        if not ip:
            QMessageBox.warning(self, "입력 오류", "IP 주소를 입력해 주세요.")
            return

        self._result_values = (nickname, ip, port)
        self.accept()

    def get_values(self) -> tuple[str, str, int] | None:
        """다이얼로그가 확인으로 닫혔다면 (닉네임, IP, 포트)를 반환."""
        return self._result_values

    @staticmethod
    def get_contact_info(parent: QWidget | None = None) -> tuple[str, str, int] | None:
        """다이얼로그를 실행하고 결과를 바로 반환하는 헬퍼."""
        dialog = AddContactDialog(parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.get_values()
        return None
