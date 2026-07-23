"""새 그룹 생성 다이얼로그 (이름 + 연락처 다중 선택)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from dochat.models.contact import Contact


class NewGroupDialog(QDialog):
    """그룹 이름 입력 + 체크박스로 연락처 다중 선택."""

    def __init__(self, contacts: list[Contact], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("새 그룹 만들기")
        self.setModal(True)
        self.setMinimumSize(320, 380)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("그룹 이름", objectName="DialogLabel"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("예: 기획팀")
        layout.addWidget(self._name_edit)

        layout.addWidget(QLabel("멤버 선택", objectName="DialogLabel"))
        self._contact_list = QListWidget()
        for contact in contacts:
            item = QListWidgetItem(contact.nickname)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, contact.id)
            self._contact_list.addItem(item)
        layout.addWidget(self._contact_list, 1)

        if not contacts:
            hint = QLabel("먼저 연락처를 추가해 주세요.")
            hint.setObjectName("DialogHint")
            layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("PrimaryButton")
        buttons.button(QDialogButtonBox.Ok).setText("만들기")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._result_values: tuple[str, list[str]] | None = None

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        member_ids = []
        for i in range(self._contact_list.count()):
            item = self._contact_list.item(i)
            if item.checkState() == Qt.Checked:
                member_ids.append(item.data(Qt.UserRole))

        if not name:
            QMessageBox.warning(self, "입력 오류", "그룹 이름을 입력해 주세요.")
            return
        if not member_ids:
            QMessageBox.warning(self, "입력 오류", "멤버를 한 명 이상 선택해 주세요.")
            return

        self._result_values = (name, member_ids)
        self.accept()

    def result_values(self) -> tuple[str, list[str]] | None:
        """다이얼로그가 확인으로 닫혔다면 (그룹이름, 멤버id리스트)를 반환."""
        return self._result_values

    @staticmethod
    def get_values(
        parent: QWidget | None, contacts: list[Contact]
    ) -> tuple[str, list[str]] | None:
        """다이얼로그를 실행하고 결과를 바로 반환하는 헬퍼."""
        dialog = NewGroupDialog(contacts, parent)
        if dialog.exec() == QDialog.Accepted:
            return dialog.result_values()
        return None
