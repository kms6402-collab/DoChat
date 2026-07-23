"""DoChat 메인 윈도우: 좌측 대화 목록 + 우측 채팅 영역."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from dochat import config
from dochat.models.message import ConversationType, MessageType
from dochat.models.storage import Storage
from dochat.network.chat_engine import ChatEngine
from dochat.network.discovery import LanDiscovery
from dochat.ui.add_contact_dialog import AddContactDialog
from dochat.ui.chat_view import ChatView
from dochat.ui.compose_bar import ComposeBar
from dochat.ui.conversation_list import ConversationList
from dochat.ui.discover_dialog import DiscoverDialog
from dochat.ui.file_room import FileRoomDialog
from dochat.ui.manage_group_dialog import ManageGroupDialog
from dochat.ui.new_group_dialog import NewGroupDialog
from dochat.ui.settings_dialog import SettingsDialog

_STYLE_PATH = Path(__file__).resolve().parent / "styles.qss"


def _tray_icon_path() -> Path:
    """트레이 아이콘 파일의 절대 경로를 반환한다.

    main.py의 resource_path()와 동일한 로직(PyInstaller 번들 시
    sys._MEIPASS 기준, 개발 환경에서는 프로젝트 루트 기준)을
    순환참조 없이 이 모듈에서 독립적으로 계산한다.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / "assets" / "icon.png"


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(config.APP_NAME)
        self.resize(1000, 700)

        self.storage = Storage(config.DB_PATH)

        # 저장된 환경설정(파일 저장 폴더 / 리스닝 포트)이 있으면 엔진 생성 전에 반영한다.
        saved_folder = self.storage.get_setting("save_folder")
        if saved_folder:
            config.RECEIVED_FILES_DIR = Path(saved_folder)
            config.RECEIVED_FILES_DIR.mkdir(parents=True, exist_ok=True)

        saved_port = self.storage.get_setting("listen_port")
        listen_port = int(saved_port) if saved_port else config.DEFAULT_LISTEN_PORT

        self.chat_engine = ChatEngine(self.storage, listen_port=listen_port)

        self.discovery = LanDiscovery(
            self.chat_engine.client_id,
            lambda: self.chat_engine.my_nickname,
            self.chat_engine.my_local_address[1],
        )
        self.discovery.start()

        self._notify_sound = self.storage.get_setting("notify_sound", "1") == "1"
        self._notify_popup = self.storage.get_setting("notify_popup", "1") == "1"

        self._current_conversation_id: str | None = None
        self._current_conversation_type: str | None = None
        self._file_room: FileRoomDialog | None = None

        # 트레이 최소화 관련 상태
        self._force_quit = False
        self._tray_hint_shown = False

        # 대화별 안읽은 메시지 개수 (conversation_id -> count, 로컬 UI 전용)
        self._unread_counts: dict[str, int] = {}

        self._build_ui()
        self._connect_signals()
        self._apply_stylesheet()

        self._refresh_lists()

        self._setup_tray_icon()

    # ------------------------------------------------------------------
    def _setup_tray_icon(self) -> None:
        """시스템 트레이 아이콘과 메뉴(열기/종료)를 구성한다."""
        self.tray_icon = QSystemTrayIcon(QIcon(str(_tray_icon_path())), self)
        self.tray_icon.setToolTip(config.APP_NAME)

        tray_menu = QMenu(self)
        open_action = tray_menu.addAction("열기")
        open_action.triggered.connect(self._on_tray_open_requested)
        quit_action = tray_menu.addAction("종료")
        quit_action.triggered.connect(self._on_tray_quit_requested)
        self.tray_icon.setContextMenu(tray_menu)

        self.tray_icon.activated.connect(self._on_tray_icon_activated)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

    def _on_tray_open_requested(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_quit_requested(self) -> None:
        self._force_quit = True
        self.close()

    def _on_tray_icon_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._on_tray_open_requested()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------------- 좌측 사이드바 ----------------
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(260)
        sidebar.setMaximumWidth(320)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("SidebarHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 16, 16, 12)
        header_layout.setSpacing(10)

        title_label = QLabel(config.APP_NAME)
        title_label.setObjectName("AppTitle")
        header_layout.addWidget(title_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self._new_contact_button = QPushButton("+ 새 대화")
        self._new_contact_button.setObjectName("SidebarActionButton")
        self._new_group_button = QPushButton("+ 새 그룹")
        self._new_group_button.setObjectName("SidebarActionButton")
        button_row.addWidget(self._new_contact_button)
        button_row.addWidget(self._new_group_button)
        header_layout.addLayout(button_row)

        self._discover_button = QPushButton("\U0001F50D 찾기")
        self._discover_button.setObjectName("SidebarActionButton")
        header_layout.addWidget(self._discover_button)

        self._file_room_button = QPushButton("\U0001F4C1 파일함 / 전송 히스토리")
        self._file_room_button.setObjectName("SidebarActionButton")
        header_layout.addWidget(self._file_room_button)

        self._settings_button = QPushButton("⚙ 설정")
        self._settings_button.setObjectName("SidebarActionButton")
        header_layout.addWidget(self._settings_button)

        sidebar_layout.addWidget(header)

        self.conversation_list = ConversationList()
        sidebar_layout.addWidget(self.conversation_list, 1)

        root.addWidget(sidebar)

        # ---------------- 우측 채팅 영역 ----------------
        chat_panel = QFrame()
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        chat_header = QFrame()
        chat_header.setObjectName("ChatHeader")
        chat_header.setFixedHeight(60)
        chat_header_layout = QVBoxLayout(chat_header)
        chat_header_layout.setContentsMargins(20, 8, 20, 8)
        chat_header_layout.setSpacing(2)
        chat_header_layout.setAlignment(Qt.AlignVCenter)

        self._header_title = QLabel("대화를 선택해 주세요")
        self._header_title.setObjectName("ChatHeaderTitle")
        self._header_subtitle = QLabel("")
        self._header_subtitle.setObjectName("ChatHeaderSubtitle")
        chat_header_layout.addWidget(self._header_title)
        chat_header_layout.addWidget(self._header_subtitle)

        chat_layout.addWidget(chat_header)

        self.chat_view = ChatView(self.chat_engine, self.storage)
        chat_layout.addWidget(self.chat_view, 1)

        self.compose_bar = ComposeBar()
        chat_layout.addWidget(self.compose_bar)

        root.addWidget(chat_panel, 1)

        self.setCentralWidget(central)

    def _apply_stylesheet(self) -> None:
        if _STYLE_PATH.exists():
            self.setStyleSheet(_STYLE_PATH.read_text(encoding="utf-8"))

    def _connect_signals(self) -> None:
        self._new_contact_button.clicked.connect(self._on_new_contact_clicked)
        self._new_group_button.clicked.connect(self._on_new_group_clicked)
        self._discover_button.clicked.connect(self._on_discover_clicked)
        self._file_room_button.clicked.connect(self._on_file_room_clicked)
        self._settings_button.clicked.connect(self._on_settings_clicked)

        self.conversation_list.conversation_selected.connect(self._on_conversation_selected)
        self.conversation_list.conversation_selected.connect(self._on_conversation_selected_clear_badge)
        self.conversation_list.edit_contact_requested.connect(self._on_edit_contact_requested)
        self.conversation_list.delete_contact_requested.connect(self._on_delete_contact_requested)
        self.conversation_list.delete_group_requested.connect(self._on_delete_group_requested)
        self.conversation_list.manage_group_requested.connect(self._on_manage_group_requested)

        self.compose_bar.text_submitted.connect(self._on_text_submitted)
        self.compose_bar.file_selected.connect(self._on_file_to_send)
        self.chat_view.file_dropped.connect(self._on_file_to_send)

        self.chat_engine.message_received.connect(self._on_message_received)
        self.chat_engine.message_received.connect(self._on_message_received_for_badge)
        self.chat_engine.message_received.connect(self._on_message_received_for_tray)
        self.chat_engine.file_progress.connect(self._on_file_progress)
        self.chat_engine.file_completed.connect(self._on_file_completed)
        self.chat_engine.file_completed.connect(self._on_file_completed_for_tray)
        self.chat_engine.contact_status_changed.connect(self._on_contact_status_changed)
        self.chat_engine.group_updated.connect(self._on_group_updated)
        self.chat_engine.messages_read_up_to.connect(self._on_messages_read_up_to)
        self.chat_engine.contact_added.connect(self._on_contact_added_by_peer)

    # ------------------------------------------------------------------
    def _refresh_lists(self) -> None:
        contacts = self.chat_engine.get_contacts()
        groups = self.chat_engine.get_groups()
        self.conversation_list.refresh(contacts, groups, self.storage)

    def _find_group_name(self, group_id: str) -> str:
        for group in self.chat_engine.get_groups():
            if group.id == group_id:
                return group.name
        return group_id

    def _update_header(self) -> None:
        if self._current_conversation_id is None:
            self._header_title.setText("대화를 선택해 주세요")
            self._header_subtitle.setText("")
            return

        if self._current_conversation_type == ConversationType.DIRECT:
            contact = self.chat_engine.get_contact(self._current_conversation_id)
            name = contact.nickname if contact else self._current_conversation_id
            online = bool(contact and contact.online)
            self._header_title.setText(name)
            self._header_subtitle.setText("온라인" if online else "오프라인")
        else:
            name = self._find_group_name(self._current_conversation_id)
            self._header_title.setText(name)
            self._header_subtitle.setText("그룹 대화")

    # ------------------------------------------------------------------
    # UI 이벤트 핸들러
    # ------------------------------------------------------------------
    def _on_new_contact_clicked(self) -> None:
        values = AddContactDialog.get_contact_info(self)
        if not values:
            return
        nickname, ip, port = values
        contact = self.chat_engine.add_contact(nickname, ip, port)
        self._refresh_lists()
        self.conversation_list.select_conversation(contact.id, ConversationType.DIRECT)
        self._on_conversation_selected(contact.id, ConversationType.DIRECT)

    def _on_new_group_clicked(self) -> None:
        contacts = self.chat_engine.get_contacts()
        if not contacts:
            QMessageBox.information(self, "알림", "먼저 대화 상대를 추가해 주세요.")
            return
        values = NewGroupDialog.get_values(self, contacts)
        if not values:
            return
        name, member_ids = values
        self.chat_engine.create_group(name, member_ids)
        self._refresh_lists()

    def _on_discover_clicked(self) -> None:
        dialog = DiscoverDialog(self.discovery, self.chat_engine, parent=self)
        dialog.exec()
        self._refresh_lists()

    def _on_file_room_clicked(self) -> None:
        if self._file_room is None:
            self._file_room = FileRoomDialog(self.chat_engine, self.storage, parent=self)
            self._file_room.finished.connect(self._on_file_room_closed)
        else:
            self._file_room.refresh()
        self._file_room.show()
        self._file_room.raise_()
        self._file_room.activateWindow()

    def _on_file_room_closed(self) -> None:
        self._file_room = None

    def _on_settings_clicked(self) -> None:
        dialog = SettingsDialog(self.chat_engine, self.storage, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self._notify_sound = self.storage.get_setting("notify_sound", "1") == "1"
            self._notify_popup = self.storage.get_setting("notify_popup", "1") == "1"
            self._update_header()
            if self._current_conversation_id is not None:
                self.chat_view.set_conversation(self._current_conversation_id, self._current_conversation_type, self.chat_engine.client_id)

    def _on_conversation_selected(self, conversation_id: str, conversation_type: str) -> None:
        self._current_conversation_id = conversation_id
        self._current_conversation_type = conversation_type
        self.chat_view.set_conversation(conversation_id, conversation_type, self.chat_engine.client_id)
        self.compose_bar.set_active(True)
        self._update_header()

    def _on_text_submitted(self, text: str) -> None:
        if self._current_conversation_id is None:
            return
        message = self.chat_engine.send_text(
            self._current_conversation_id, self._current_conversation_type, text
        )
        self.chat_view.append_message(message)
        self.conversation_list.update_preview(
            self._current_conversation_id, self._current_conversation_type, self.storage
        )

    def _on_file_to_send(self, file_path: str) -> None:
        if self._current_conversation_id is None:
            QMessageBox.information(self, "알림", "먼저 대화를 선택해 주세요.")
            return
        # send_file()은 FileRecord만 즉시 저장하고 Message는 전송 완료 시점에
        # 저장되므로, 진행 중 버블은 file_progress 시그널에서 즉석 생성된다
        # (ChatView.ensure_file_bubble 참고).
        self.chat_engine.send_file(
            self._current_conversation_id, self._current_conversation_type, file_path
        )

    def _clear_current_conversation(self) -> None:
        """현재 열려 있는 대화 화면을 비우고 선택을 해제한다."""
        self._current_conversation_id = None
        self._current_conversation_type = None
        self.chat_view.clear()
        self.compose_bar.set_active(False)
        self._update_header()

    def _on_edit_contact_requested(self, contact_id: str) -> None:
        contact = self.chat_engine.get_contact(contact_id)
        if contact is None:
            return
        values = AddContactDialog.get_contact_info(
            self, initial=(contact.nickname, contact.ip, contact.port)
        )
        if not values:
            return
        nickname, ip, port = values
        self.chat_engine.update_contact(contact_id, nickname, ip, port)
        self._refresh_lists()
        if self._current_conversation_id == contact_id:
            self._update_header()

    def _on_delete_contact_requested(self, contact_id: str) -> None:
        contact = self.chat_engine.get_contact(contact_id)
        name = contact.nickname if contact else contact_id
        answer = QMessageBox.question(
            self,
            "연락처 삭제",
            f"'{name}' 연락처를 정말 삭제하시겠습니까?",
        )
        if answer != QMessageBox.Yes:
            return
        self.chat_engine.remove_contact(contact_id)
        if (
            self._current_conversation_type == ConversationType.DIRECT
            and self._current_conversation_id == contact_id
        ):
            self._clear_current_conversation()
        self._refresh_lists()

    def _on_delete_group_requested(self, group_id: str) -> None:
        name = self._find_group_name(group_id)
        answer = QMessageBox.question(
            self,
            "그룹 나가기",
            f"'{name}' 그룹에서 나가시겠습니까? (목록에서 삭제됩니다)",
        )
        if answer != QMessageBox.Yes:
            return
        self.chat_engine.leave_group(group_id)
        if (
            self._current_conversation_type == ConversationType.GROUP
            and self._current_conversation_id == group_id
        ):
            self._clear_current_conversation()
        self._refresh_lists()

    def _on_manage_group_requested(self, group_id: str) -> None:
        group = None
        for g in self.chat_engine.get_groups():
            if g.id == group_id:
                group = g
                break
        if group is None:
            return
        ManageGroupDialog.manage(self, self.chat_engine, group)
        self._refresh_lists()

    # ------------------------------------------------------------------
    # ChatEngine 시그널 핸들러
    # ------------------------------------------------------------------
    def _on_message_received(self, message) -> None:
        if self._notify_sound:
            QApplication.beep()
        if (
            self._current_conversation_id == message.conversation_id
            and self._current_conversation_type == message.conversation_type
        ):
            self.chat_view.append_message(message)
        self.conversation_list.update_preview(
            message.conversation_id, message.conversation_type, self.storage
        )

    def _on_message_received_for_badge(self, message) -> None:
        """현재 열려있지 않은 대화에 새 메시지가 오면 안읽은 배지를 갱신한다.

        (로컬 UI 전용 상태 — 기존 _on_message_received와는 별도의 슬롯으로 동작한다.)
        """
        if (
            self._current_conversation_id == message.conversation_id
            and self._current_conversation_type == message.conversation_type
        ):
            return
        self._unread_counts[message.conversation_id] = (
            self._unread_counts.get(message.conversation_id, 0) + 1
        )
        self.conversation_list.set_unread_count(
            message.conversation_id,
            message.conversation_type,
            self._unread_counts[message.conversation_id],
        )

    def _on_message_received_for_tray(self, message) -> None:
        """창이 트레이에 내려가 있을 때 새 메시지를 트레이 풍선 알림으로 표시한다.

        (로컬 UI 전용 상태 — 기존 _on_message_received와는 별도의 슬롯으로 동작한다.)
        """
        if not self._notify_popup or self.isVisible():
            return
        if message.sender_id == self.chat_engine.client_id:
            return

        contact = self.chat_engine.get_contact(message.sender_id)
        sender_name = contact.nickname if contact else message.sender_id

        if message.conversation_type == ConversationType.GROUP:
            group_name = self._find_group_name(message.conversation_id)
            title = f"{group_name} - {sender_name}"
        else:
            title = sender_name

        if message.type == MessageType.FILE:
            body = "파일을 보냈습니다."
        else:
            body = message.text or ""

        self.tray_icon.showMessage(title, body, QSystemTrayIcon.Information, 4000)

    def _on_file_completed_for_tray(self, file_id: str, success: bool) -> None:
        """창이 트레이에 내려가 있을 때 파일 수신 완료를 트레이 풍선 알림으로 표시한다."""
        if not self._notify_popup or self.isVisible() or not success:
            return
        record = self.storage.get_file_record(file_id)
        if record is None or record.direction != "in":
            return
        self.tray_icon.showMessage(
            "DoChat", f"파일 수신 완료: {record.filename}", QSystemTrayIcon.Information, 4000
        )

    def _on_conversation_selected_clear_badge(self, conversation_id: str, conversation_type: str) -> None:
        """대화를 선택하면 해당 대화의 안읽은 배지를 초기화한다."""
        self._unread_counts[conversation_id] = 0
        self.conversation_list.set_unread_count(conversation_id, conversation_type, 0)

    def _on_file_progress(self, file_id: str, done: int, total: int, direction: str) -> None:
        # message_received 없이도 진행 중인 파일을 보여주기 위해 필요하면 임시 버블을 생성한다.
        self.chat_view.ensure_file_bubble(file_id)
        self.chat_view.update_file_progress(file_id, done, total)
        if self._file_room is not None:
            self._file_room.refresh()

    def _on_file_completed(self, file_id: str, success: bool) -> None:
        record = self.storage.get_file_record(file_id)
        conversation_id = record.conversation_id if record else None

        if self._notify_sound and success and record is not None and record.direction == "in":
            QApplication.beep()

        if conversation_id is not None and conversation_id == self._current_conversation_id:
            # 완료 시점에 실제 Message가 storage에 저장되므로 현재 대화를 다시 로드해
            # 임시 버블을 최종 상태(썸네일/파일카드)로 교체한다.
            self.chat_view.set_conversation(
                self._current_conversation_id,
                self._current_conversation_type,
                self.chat_engine.client_id,
            )
        else:
            self.chat_view.mark_file_completed(file_id, success)

        if self._file_room is not None:
            self._file_room.refresh()

        self._refresh_lists()

    def _on_contact_status_changed(self, contact_id: str, online: bool) -> None:
        self.conversation_list.update_presence(contact_id, online)
        if (
            self._current_conversation_type == ConversationType.DIRECT
            and self._current_conversation_id == contact_id
        ):
            self._update_header()

    def _on_messages_read_up_to(self, conversation_id: str, up_to_ts: float) -> None:
        """상대가 내 메시지를 읽었다는 확인(READ_RECEIPT)이 도착했을 때, 현재
        열려 있는 대화면 해당 버블들에 '읽음' 표시를 갱신한다."""
        if self._current_conversation_id != conversation_id:
            return
        self.chat_view.mark_messages_read_up_to(conversation_id, up_to_ts)

    def _on_group_updated(self, group_id: str) -> None:
        self._refresh_lists()
        if (
            self._current_conversation_type == ConversationType.GROUP
            and self._current_conversation_id == group_id
        ):
            self._update_header()

    def _on_contact_added_by_peer(self, contact_id: str) -> None:
        """상대방이 나를 연락처로 추가했다는 HELLO를 받았을 때, 내 목록에도
        해당 연락처를 반영하고 그 대화를 자동으로 연다."""
        self._refresh_lists()
        self.conversation_list.select_conversation(contact_id, ConversationType.DIRECT)
        self._on_conversation_selected(contact_id, ConversationType.DIRECT)

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        if not self._force_quit and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.tray_icon.showMessage(
                    "DoChat",
                    "트레이에서 계속 실행됩니다.",
                    QSystemTrayIcon.Information,
                    3000,
                )
                self._tray_hint_shown = True
            return

        try:
            self.storage.close()
        except Exception:
            pass
        super().closeEvent(event)
