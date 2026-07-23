"""그룹 멤버 관리 다이얼로그: 현재 멤버 제거 / 신규 멤버 추가.

새 그룹 만들기(NewGroupDialog)와 달리, 이 다이얼로그는 확인/취소 없이 각
버튼(제거/추가)을 누르는 즉시 ChatEngine을 통해 실제로 반영되고 다른 멤버들에게도
전파된다. 그래야 "제거하자마자 바로 반영"되는 자연스러운 UX가 된다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dochat.models.contact import Group
from dochat.network.chat_engine import ChatEngine


class _MemberRow(QWidget):
    def __init__(self, nickname: str, contact_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        label = QLabel(nickname)
        layout.addWidget(label, 1)
        self.remove_button = QPushButton("제거")
        self.remove_button.setObjectName("DangerButton")
        layout.addWidget(self.remove_button)
        self.contact_id = contact_id


class ManageGroupDialog(QDialog):
    """현재 그룹 멤버 목록 + 제거 버튼, 그리고 비멤버 연락처 다중 선택 + 추가 버튼."""

    def __init__(self, chat_engine: ChatEngine, group_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._chat_engine = chat_engine
        self._group_id = group_id

        self.setModal(True)
        self.setMinimumSize(340, 460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("현재 멤버", objectName="DialogLabel"))
        self._member_list = QListWidget()
        layout.addWidget(self._member_list, 1)

        layout.addWidget(QLabel("멤버 추가", objectName="DialogLabel"))
        self._candidate_list = QListWidget()
        layout.addWidget(self._candidate_list, 1)

        self._add_button = QPushButton("선택한 연락처 추가")
        self._add_button.setObjectName("PrimaryButton")
        self._add_button.clicked.connect(self._on_add_clicked)
        layout.addWidget(self._add_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("닫기")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

        self._refresh()

    # ------------------------------------------------------------------
    def _current_group(self) -> Group | None:
        for group in self._chat_engine.get_groups():
            if group.id == self._group_id:
                return group
        return None

    def _refresh(self) -> None:
        group = self._current_group()
        if group is None:
            # 내가 제거되었거나 그룹이 사라진 경우: 다이얼로그를 닫는다.
            self.accept()
            return

        self.setWindowTitle(f"멤버 관리 - {group.name}")

        self._member_list.clear()
        for member_id in group.member_ids:
            contact = self._chat_engine.get_contact(member_id)
            nickname = contact.nickname if contact else member_id
            row = _MemberRow(nickname, member_id)
            row.remove_button.clicked.connect(
                lambda _checked=False, cid=member_id: self._on_remove_clicked(cid)
            )
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self._member_list.addItem(item)
            self._member_list.setItemWidget(item, row)

        member_ids = set(group.member_ids)
        self._candidate_list.clear()
        for contact in self._chat_engine.get_contacts():
            if contact.id in member_ids:
                continue
            item = QListWidgetItem(contact.nickname)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, contact.id)
            self._candidate_list.addItem(item)

    # ------------------------------------------------------------------
    def _on_remove_clicked(self, contact_id: str) -> None:
        self._chat_engine.remove_group_member(self._group_id, contact_id)
        self._refresh()

    def _on_add_clicked(self) -> None:
        selected_ids = []
        for i in range(self._candidate_list.count()):
            item = self._candidate_list.item(i)
            if item.checkState() == Qt.Checked:
                selected_ids.append(item.data(Qt.UserRole))
        if not selected_ids:
            return
        self._chat_engine.add_group_members(self._group_id, selected_ids)
        self._refresh()

    # ------------------------------------------------------------------
    @staticmethod
    def manage(parent: QWidget | None, chat_engine: ChatEngine, group: Group) -> None:
        """다이얼로그를 실행하는 헬퍼. 반환값 없이(즉시 반영 방식) 내부에서 종료된다."""
        dialog = ManageGroupDialog(chat_engine, group.id, parent)
        dialog.exec()
