"""LAN에서 자동 탐색된 DoChat 사용자를 보여주고 연락처로 추가하는 다이얼로그."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dochat.network.discovery import LanDiscovery


class DiscoverDialog(QDialog):
    """`LanDiscovery`가 찾아낸 피어 목록을 실시간으로 표시하고, 선택 시 연락처로 추가한다."""

    def __init__(self, discovery: LanDiscovery, chat_engine, parent: QWidget | None = None):
        super().__init__(parent)
        self._discovery = discovery
        self._chat_engine = chat_engine
        # client_id -> QListWidgetItem (중복 표시 방지용)
        self._items: dict[str, QListWidgetItem] = {}

        self.setWindowTitle("같은 네트워크에서 찾기")
        self.setModal(True)
        self.setMinimumSize(420, 360)

        layout = QVBoxLayout(self)

        info_label = QLabel("같은 LAN에 있는 DoChat 사용자를 자동으로 찾습니다. 목록에서 더블클릭하거나 '추가' 버튼을 눌러 대화 상대로 등록하세요.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._add_button = QPushButton("추가")
        self._add_button.setObjectName("PrimaryButton")
        self._add_button.clicked.connect(self._on_add_clicked)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.reject)
        button_row.addWidget(self._add_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self._discovery.peer_discovered.connect(self._on_peer_discovered)

        self._load_existing_peers()

    def _load_existing_peers(self) -> None:
        for info in self._discovery.discovered_peers():
            self._upsert_item(info["client_id"], info["nickname"], info["ip"], info["chat_port"])

    def _on_peer_discovered(self, client_id: str, nickname: str, ip: str, chat_port: int) -> None:
        self._upsert_item(client_id, nickname, ip, chat_port)

    def _upsert_item(self, client_id: str, nickname: str, ip: str, chat_port: int) -> None:
        text = f"{nickname}  ({ip}:{chat_port})"
        item = self._items.get(client_id)
        if item is None:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, {"client_id": client_id, "nickname": nickname, "ip": ip, "chat_port": chat_port})
            self._list.addItem(item)
            self._items[client_id] = item
        else:
            item.setText(text)
            item.setData(Qt.UserRole, {"client_id": client_id, "nickname": nickname, "ip": ip, "chat_port": chat_port})

    def _on_add_clicked(self) -> None:
        item = self._list.currentItem()
        if item is None:
            QMessageBox.information(self, "알림", "먼저 목록에서 추가할 상대를 선택해 주세요.")
            return
        self._add_peer(item)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._add_peer(item)

    def _add_peer(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if not data:
            return
        self._chat_engine.add_contact(data["nickname"], data["ip"], data["chat_port"])
        QMessageBox.information(self, "완료", f"'{data['nickname']}'님을 대화 상대로 추가했습니다.")
