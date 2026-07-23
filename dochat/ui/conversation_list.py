"""좌측 사이드바: 연락처(1:1)와 그룹을 함께 나열하는 대화 목록."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dochat.models.contact import Contact, Group
from dochat.models.message import ConversationType, MessageType
from dochat.models.storage import Storage

ONLINE_COLOR = "#34C77B"
OFFLINE_COLOR = "#B7BBC2"


class _StatusDot(QLabel):
    """온라인 상태를 나타내는 작은 원."""

    def __init__(self, online: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(9, 9)
        self.set_online(online)

    def set_online(self, online: bool) -> None:
        color = ONLINE_COLOR if online else OFFLINE_COLOR
        self.setStyleSheet(
            f"background-color: {color}; border-radius: 4px; border: none;"
        )


class _ConversationRow(QWidget):
    """리스트 항목 하나에 들어가는 커스텀 위젯 (아이콘/이름/미리보기)."""

    def __init__(
        self,
        title: str,
        preview: str,
        is_group: bool,
        online: bool | None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # 아바타 자리: 원형 배경 + 이니셜
        avatar = QLabel(title[:1].upper() if title else "?")
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignCenter)
        avatar_bg = "#3B6FE0" if is_group else "#8A8F98"
        avatar.setStyleSheet(
            f"background-color: {avatar_bg}; color: #FFFFFF; border-radius: 18px;"
            f"font-weight: 600; font-size: 14px;"
        )
        layout.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 600; font-size: 13px; background: transparent;")
        title_row.addWidget(title_label)

        self.status_dot: _StatusDot | None = None
        if not is_group:
            self.status_dot = _StatusDot(bool(online))
            title_row.addWidget(self.status_dot)
        title_row.addStretch(1)
        text_col.addLayout(title_row)

        self.preview_label = QLabel(preview)
        self.preview_label.setStyleSheet(
            "color: #8A8F98; font-size: 11px; background: transparent;"
        )
        self.preview_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        fm = self.preview_label.fontMetrics()
        self.preview_label.setText(fm.elidedText(preview, Qt.ElideRight, 200))
        text_col.addWidget(self.preview_label)

        layout.addLayout(text_col, 1)

        # 안읽은 메시지 개수 배지 (0이면 숨김)
        self.unread_badge = QLabel("")
        self.unread_badge.setFixedSize(20, 20)
        self.unread_badge.setAlignment(Qt.AlignCenter)
        self.unread_badge.setStyleSheet(
            "background-color: #E0433B; color: #FFFFFF; border-radius: 10px;"
            "font-weight: 600; font-size: 10px;"
        )
        self.unread_badge.hide()
        layout.addWidget(self.unread_badge)

    def set_unread(self, count: int) -> None:
        """안읽은 메시지 개수 배지를 갱신한다. count가 0이면 숨긴다."""
        if count <= 0:
            self.unread_badge.hide()
            self.unread_badge.setText("")
            return
        self.unread_badge.setText(str(count) if count <= 99 else "99+")
        self.unread_badge.show()


def _format_preview(storage: Storage, conversation_id: str) -> str:
    last = storage.get_last_message(conversation_id)
    if last is None:
        return "대화 내역이 없습니다"
    if last.type == MessageType.FILE:
        record = storage.get_file_record(last.file_id) if last.file_id else None
        name = record.filename if record else "파일"
        return f"\U0001F4CE {name}"
    return last.text or ""


class ConversationList(QWidget):
    """연락처와 그룹을 함께 보여주는 대화 목록 사이드바."""

    conversation_selected = Signal(str, str)  # conversation_id, conversation_type
    edit_contact_requested = Signal(str)      # contact_id
    delete_contact_requested = Signal(str)    # contact_id
    delete_group_requested = Signal(str)      # group_id
    manage_group_requested = Signal(str)      # group_id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setObjectName("ConversationList")
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu_requested)
        layout.addWidget(self._list)

        # (conversation_id, conversation_type) -> QListWidgetItem
        self._items: dict[tuple[str, str], QListWidgetItem] = {}

    # ------------------------------------------------------------------
    def refresh(self, contacts: list[Contact], groups: list[Group], storage: Storage) -> None:
        """연락처/그룹 목록으로 전체를 다시 그린다."""
        selected_key = self.current_selection()

        self._list.clear()
        self._items.clear()

        for contact in contacts:
            key = (contact.id, ConversationType.DIRECT)
            preview = _format_preview(storage, contact.id)
            row = _ConversationRow(contact.nickname, preview, is_group=False, online=contact.online)
            self._add_row(key, row)

        for group in groups:
            key = (group.id, ConversationType.GROUP)
            preview = _format_preview(storage, group.id)
            row = _ConversationRow(group.name, preview, is_group=True, online=None)
            self._add_row(key, row)

        if selected_key is not None and selected_key in self._items:
            self._list.setCurrentItem(self._items[selected_key])

    def _add_row(self, key: tuple[str, str], row: _ConversationRow) -> None:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, key)
        item.setSizeHint(row.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, row)
        self._items[key] = item

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.UserRole)
        if key is None:
            return
        conversation_id, conversation_type = key
        self.conversation_selected.emit(conversation_id, conversation_type)

    def _on_context_menu_requested(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        key = item.data(Qt.UserRole)
        if key is None:
            return
        conversation_id, conversation_type = key

        menu = QMenu(self)
        if conversation_type == ConversationType.DIRECT:
            edit_action = menu.addAction("편집")
            delete_action = menu.addAction("삭제")
            chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
            if chosen is edit_action:
                self.edit_contact_requested.emit(conversation_id)
            elif chosen is delete_action:
                self.delete_contact_requested.emit(conversation_id)
        else:
            manage_action = menu.addAction("멤버 관리")
            leave_action = menu.addAction("그룹 나가기(삭제)")
            chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
            if chosen is manage_action:
                self.manage_group_requested.emit(conversation_id)
            elif chosen is leave_action:
                self.delete_group_requested.emit(conversation_id)

    def current_selection(self) -> tuple[str, str] | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def update_presence(self, contact_id: str, online: bool) -> None:
        """특정 연락처의 온라인 상태 점만 갱신한다."""
        key = (contact_id, ConversationType.DIRECT)
        item = self._items.get(key)
        if item is None:
            return
        row = self._list.itemWidget(item)
        if isinstance(row, _ConversationRow) and row.status_dot is not None:
            row.status_dot.set_online(online)

    def update_preview(self, conversation_id: str, conversation_type: str, storage: Storage) -> None:
        """특정 대화의 마지막 메시지 미리보기만 갱신한다."""
        key = (conversation_id, conversation_type)
        item = self._items.get(key)
        if item is None:
            return
        row = self._list.itemWidget(item)
        if isinstance(row, _ConversationRow):
            preview = _format_preview(storage, conversation_id)
            fm = row.preview_label.fontMetrics()
            row.preview_label.setText(fm.elidedText(preview, Qt.ElideRight, 200))

    def set_unread_count(self, conversation_id: str, conversation_type: str, count: int) -> None:
        """특정 대화의 안읽은 메시지 배지를 갱신한다 (로컬 UI 전용 상태)."""
        key = (conversation_id, conversation_type)
        item = self._items.get(key)
        if item is None:
            return
        row = self._list.itemWidget(item)
        if isinstance(row, _ConversationRow):
            row.set_unread(count)
