"""좌측 사이드바: 연락처(1:1)와 그룹을 함께 나열하는 대화 목록."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dochat.config import AVATAR_DIR
from dochat.models.contact import Contact, Group
from dochat.models.message import ConversationType, MessageType
from dochat.models.storage import Storage
from dochat.ui.avatar_widget import AvatarWidget, GROUP_AVATAR_COLOR, avatar_color_for

ONLINE_COLOR = "#22C55E"
OFFLINE_COLOR = "#9CA3AF"

AVATAR_SIZE = 44
STATUS_DOT_SIZE = 14
# 아바타 배지를 담는 컨테이너는 상태 점이 아바타 우측 하단 모서리 밖으로
# 살짝 걸치도록(overlay) 아바타보다 약간 더 크게 잡는다.
_BADGE_PAD = 4
BADGE_CONTAINER_SIZE = AVATAR_SIZE + _BADGE_PAD


class _StatusDot(QLabel):
    """온라인 상태를 뚜렷하게 보여주는 배지형 원 (아바타 모서리에 겹쳐 표시)."""

    def __init__(self, online: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(STATUS_DOT_SIZE, STATUS_DOT_SIZE)
        self.set_online(online)

    def set_online(self, online: bool) -> None:
        color = ONLINE_COLOR if online else OFFLINE_COLOR
        self.setStyleSheet(
            f"background-color: {color}; border-radius: {STATUS_DOT_SIZE // 2}px;"
            f"border: 2px solid #FFFFFF;"
        )


class _AvatarBadge(QWidget):
    """원형 아바타(이니셜)와, 1:1 연락처의 경우 우측 하단에 겹치는 온라인 상태 점을 담는 컨테이너.

    카카오톡/슬랙류 메신저처럼 상태 점을 아바타 위에 오버레이하는 방식을 사용해
    이름 옆 텍스트 라인이 아니라 시각적으로 가장 먼저 눈에 띄는 위치에서
    온라인/오프라인을 구분할 수 있게 한다.
    """

    def __init__(
        self,
        title: str,
        is_group: bool,
        online: bool | None,
        avatar_color: str,
        photo_path: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setFixedSize(BADGE_CONTAINER_SIZE, BADGE_CONTAINER_SIZE)

        # 그룹은 항상 고정된 앰버색으로, 연락처는 참고 디자인처럼 사람마다
        # 다른(하지만 id 기반으로 항상 안정적인) 색으로 구분한다.
        self.avatar = AvatarWidget(
            AVATAR_SIZE,
            initial=title[:1] if title else "?",
            bg_color=avatar_color,
            photo_path=photo_path,
            parent=self,
        )
        self.avatar.move(0, 0)

        self.status_dot: _StatusDot | None = None
        if not is_group:
            self.status_dot = _StatusDot(bool(online), self)
            offset = BADGE_CONTAINER_SIZE - STATUS_DOT_SIZE
            self.status_dot.move(offset, offset)
            self.status_dot.raise_()

    def set_photo_path(self, photo_path: str | None) -> None:
        self.avatar.set_photo_path(photo_path)


class _ConversationRow(QWidget):
    """리스트 항목 하나에 들어가는 커스텀 위젯 (아이콘/이름/미리보기)."""

    def __init__(
        self,
        title: str,
        preview: str,
        is_group: bool,
        online: bool | None,
        avatar_color: str,
        photo_path: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # 아바타 + 온라인 상태 배지 (1:1 연락처는 우측 하단에 상태 점이 겹쳐 보인다)
        self._avatar_badge = _AvatarBadge(title, is_group, online, avatar_color, photo_path=photo_path)
        layout.addWidget(self._avatar_badge)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 700; font-size: 14px; background: transparent;")
        title_row.addWidget(title_label)

        # 상태 점은 아바타 위에 겹쳐 표시하지만, 온라인/오프라인 여부를
        # 텍스트로도 짧게 병기해 색맹 사용자나 작은 화면에서도 명확히 구분되게 한다.
        self.presence_label: QLabel | None = None
        if not is_group:
            self.presence_label = QLabel()
            self.presence_label.setStyleSheet("font-size: 10px; font-weight: 600; background: transparent;")
            self._update_presence_label(bool(online))
            title_row.addWidget(self.presence_label)

        self.status_dot: _StatusDot | None = self._avatar_badge.status_dot
        title_row.addStretch(1)
        text_col.addLayout(title_row)

        self.preview_label = QLabel(preview)
        self.preview_label.setStyleSheet(
            "color: #ABA6C6; font-size: 11px; background: transparent;"
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

    def _update_presence_label(self, online: bool) -> None:
        if self.presence_label is None:
            return
        if online:
            self.presence_label.setText("온라인")
            self.presence_label.setStyleSheet(
                f"color: {ONLINE_COLOR}; font-size: 10px; font-weight: 700; background: transparent;"
            )
        else:
            self.presence_label.setText("오프라인")
            self.presence_label.setStyleSheet(
                f"color: {OFFLINE_COLOR}; font-size: 10px; font-weight: 600; background: transparent;"
            )

    def set_online(self, online: bool) -> None:
        """온라인 상태 배지(아바타 위 점)와 텍스트 표시를 함께 갱신한다."""
        if self.status_dot is not None:
            self.status_dot.set_online(online)
        self._update_presence_label(online)

    def set_avatar_photo(self, photo_path: str | None) -> None:
        self._avatar_badge.set_photo_path(photo_path)


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

    conversation_selected = Signal(str, str)      # conversation_id, conversation_type
    edit_contact_requested = Signal(str)          # contact_id
    delete_contact_requested = Signal(str)        # contact_id
    delete_group_requested = Signal(str)          # group_id
    manage_group_requested = Signal(str)          # group_id
    favorite_toggle_requested = Signal(str, str)  # conversation_id, conversation_type

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._search_input = QLineEdit()
        self._search_input.setObjectName("SearchInput")
        self._search_input.setPlaceholderText("이름으로 검색")
        self._search_input.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self._search_input)

        self._list = QListWidget()
        self._list.setObjectName("ConversationList")
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu_requested)
        layout.addWidget(self._list)

        # (conversation_id, conversation_type) -> QListWidgetItem (섹션 헤더는 제외, 실제 데이터 행만)
        self._items: dict[tuple[str, str], QListWidgetItem] = {}
        # (conversation_id, conversation_type) -> 표시 이름 (검색 필터링용)
        self._titles: dict[tuple[str, str], str] = {}
        # 섹션 헤더 항목과 그 아래 속한 데이터 행 항목들의 목록 (검색 시 헤더 표시 여부 계산용)
        self._sections: list[tuple[QListWidgetItem, list[QListWidgetItem]]] = []
        # 현재 즐겨찾기로 표시된 대화 키 집합 (컨텍스트 메뉴에서 참조)
        self._favorites: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    def refresh(
        self,
        contacts: list[Contact],
        groups: list[Group],
        storage: Storage,
        favorites: set[tuple[str, str]] | None = None,
    ) -> None:
        """연락처/그룹 목록으로 전체를 다시 그린다.

        즐겨찾기(favorites)로 표시된 대화는 종류(연락처/그룹)와 무관하게
        맨 위 "⭐ 즐겨찾기" 섹션에 먼저 모이고, 나머지는 "연락처"/"그룹"
        섹션으로 나뉜다. 각 섹션은 속한 항목이 하나도 없으면 헤더째로 생략한다.
        """
        self._favorites = set(favorites) if favorites else set()
        selected_key = self.current_selection()

        self._list.clear()
        self._items.clear()
        self._titles.clear()
        self._sections = []

        # 온라인인 연락처를 먼저 보여줘서 한눈에 지금 대화 가능한 상대를 파악하기 쉽게 한다.
        # (그룹은 정렬 대상이 아니며 항상 연락처 다음 섹션에 그대로 붙는다.)
        sorted_contacts = sorted(contacts, key=lambda c: not c.online)

        favorite_contacts = [c for c in sorted_contacts if (c.id, ConversationType.DIRECT) in self._favorites]
        normal_contacts = [c for c in sorted_contacts if (c.id, ConversationType.DIRECT) not in self._favorites]
        favorite_groups = [g for g in groups if (g.id, ConversationType.GROUP) in self._favorites]
        normal_groups = [g for g in groups if (g.id, ConversationType.GROUP) not in self._favorites]

        if favorite_contacts or favorite_groups:
            header = self._add_section_header("⭐ 즐겨찾기")
            rows = [self._add_contact_row(contact, storage) for contact in favorite_contacts]
            rows += [self._add_group_row(group, storage) for group in favorite_groups]
            self._sections.append((header, rows))

        if normal_contacts:
            header = self._add_section_header("연락처")
            rows = [self._add_contact_row(contact, storage) for contact in normal_contacts]
            self._sections.append((header, rows))

        if normal_groups:
            header = self._add_section_header("그룹")
            rows = [self._add_group_row(group, storage) for group in normal_groups]
            self._sections.append((header, rows))

        if selected_key is not None and selected_key in self._items:
            self._list.setCurrentItem(self._items[selected_key])

        # 검색어가 남아 있는 상태로 refresh가 호출될 수도 있으므로(예: 새 메시지
        # 수신) 항상 현재 검색어 기준으로 필터를 다시 적용한다.
        self._apply_filter(self._search_input.text())

    def _add_section_header(self, text: str) -> QListWidgetItem:
        """선택 불가능한 슬림 구분선 행으로 섹션 헤더를 추가한다."""
        item = QListWidgetItem()
        item.setFlags(Qt.NoItemFlags)
        item.setSizeHint(QSize(0, 28))
        self._list.addItem(item)
        label = QLabel(text)
        label.setObjectName("ListSectionLabel")
        self._list.setItemWidget(item, label)
        return item

    def _add_contact_row(self, contact: Contact, storage: Storage) -> QListWidgetItem:
        key = (contact.id, ConversationType.DIRECT)
        preview = _format_preview(storage, contact.id)
        photo_path = str(AVATAR_DIR / f"{contact.id}.jpg")
        row = _ConversationRow(
            contact.nickname,
            preview,
            is_group=False,
            online=contact.online,
            avatar_color=avatar_color_for(contact.id),
            photo_path=photo_path,
        )
        return self._add_row(key, row, contact.nickname)

    def _add_group_row(self, group: Group, storage: Storage) -> QListWidgetItem:
        key = (group.id, ConversationType.GROUP)
        preview = _format_preview(storage, group.id)
        row = _ConversationRow(
            group.name,
            preview,
            is_group=True,
            online=None,
            avatar_color=GROUP_AVATAR_COLOR,
        )
        return self._add_row(key, row, group.name)

    def _add_row(self, key: tuple[str, str], row: _ConversationRow, title: str) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, key)
        item.setSizeHint(row.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, row)
        self._items[key] = item
        self._titles[key] = title
        return item

    # ------------------------------------------------------------------
    def _on_search_text_changed(self, text: str) -> None:
        self._apply_filter(text)

    def _apply_filter(self, text: str) -> None:
        """검색어(대소문자 무시, 부분 문자열)로 데이터 행을 보이거나 숨긴다.

        데이터 행을 먼저 필터링한 뒤, 각 섹션 헤더는 그 아래 보이는 행이
        하나라도 있으면 보이고 없으면 함께 숨기는 2차 패스로 처리한다.
        """
        query = text.strip().lower()
        for key, item in self._items.items():
            title = self._titles.get(key, "")
            hide = bool(query) and query not in title.lower()
            self._list.setRowHidden(self._list.row(item), hide)

        for header_item, row_items in self._sections:
            any_visible = any(
                not self._list.isRowHidden(self._list.row(row_item)) for row_item in row_items
            )
            self._list.setRowHidden(self._list.row(header_item), not any_visible)

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

        is_favorite = key in self._favorites
        favorite_label = "⭐ 즐겨찾기 해제" if is_favorite else "☆ 즐겨찾기 추가"

        menu = QMenu(self)
        if conversation_type == ConversationType.DIRECT:
            edit_action = menu.addAction("편집")
            delete_action = menu.addAction("삭제")
            favorite_action = menu.addAction(favorite_label)
            chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
            if chosen is edit_action:
                self.edit_contact_requested.emit(conversation_id)
            elif chosen is delete_action:
                self.delete_contact_requested.emit(conversation_id)
            elif chosen is favorite_action:
                self.favorite_toggle_requested.emit(conversation_id, conversation_type)
        else:
            manage_action = menu.addAction("멤버 관리")
            leave_action = menu.addAction("그룹 나가기(삭제)")
            favorite_action = menu.addAction(favorite_label)
            chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
            if chosen is manage_action:
                self.manage_group_requested.emit(conversation_id)
            elif chosen is leave_action:
                self.delete_group_requested.emit(conversation_id)
            elif chosen is favorite_action:
                self.favorite_toggle_requested.emit(conversation_id, conversation_type)

    def select_conversation(self, conversation_id: str, conversation_type: str) -> None:
        """해당 대화 항목을 시각적으로만 선택 상태로 맞춘다 (시그널 emit 없음).

        실제 대화 전환 로직은 호출 측(MainWindow)이 별도로 처리한다. 항목이
        아직 목록에 없으면(막 추가되어 refresh 전이라면) 아무 것도 하지 않는다.
        """
        key = (conversation_id, conversation_type)
        item = self._items.get(key)
        if item is None:
            return
        self._list.setCurrentItem(item)

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
        if isinstance(row, _ConversationRow):
            row.set_online(online)

    def update_avatar(self, contact_id: str) -> None:
        """상대의 프로필 사진이 새로 도착했을 때(avatar_updated 시그널) 해당
        행의 아바타만 다시 그린다."""
        key = (contact_id, ConversationType.DIRECT)
        item = self._items.get(key)
        if item is None:
            return
        row = self._list.itemWidget(item)
        if isinstance(row, _ConversationRow):
            row.set_avatar_photo(str(AVATAR_DIR / f"{contact_id}.jpg"))

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
