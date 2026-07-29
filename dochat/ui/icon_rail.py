"""좌측 아이콘 레일: 항상 짙은 네이비 톤으로 고정된, 앱의 최상위 내비게이션.

참고 디자인(팀즈 스타일)처럼 대화 목록 패널과는 별도의 얇은 다크 레일을 두고,
그 안에서 선택된 항목만 액센트 컬러로 강조 표시한다. DoChat에는 "채널/팀" 같은
개념이 없으므로, 이미 있는 기능(채팅 화면/찾기(LAN 피어 검색)/파일함/설정)을
그대로 아이콘으로 배치한다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QPushButton, QVBoxLayout, QWidget

from dochat.ui.avatar_widget import AvatarWidget

RAIL_WIDTH = 64


class _RailButton(QPushButton):
    def __init__(self, icon: str, label: str, parent: QWidget | None = None):
        super().__init__(f"{icon}\n{label}", parent)
        self.setObjectName("IconRailButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(RAIL_WIDTH - 12, RAIL_WIDTH - 16)


class IconRail(QWidget):
    """항상 보이는 좌측 아이콘 레일. 채팅 화면 전환은 없지만(단일 화면 앱),
    파일함/찾기/설정처럼 별도 창을 여는 동작들을 아이콘으로 노출한다."""

    chat_clicked = Signal()
    discover_clicked = Signal()
    file_room_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("IconRail")
        self.setFixedWidth(RAIL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 16, 6, 12)
        layout.setSpacing(6)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        self._chat_button = _RailButton("\U0001F4AC", "채팅")  # 💬
        self._chat_button.setChecked(True)  # DoChat은 화면이 하나뿐이라 항상 활성 상태
        self._chat_button.clicked.connect(self.chat_clicked.emit)
        self._group.addButton(self._chat_button)
        layout.addWidget(self._chat_button)

        self._discover_button = _RailButton("\U0001F50D", "찾기")  # 🔍
        self._discover_button.clicked.connect(self._on_transient_action(self.discover_clicked))
        self._group.addButton(self._discover_button)
        layout.addWidget(self._discover_button)

        self._file_room_button = _RailButton("\U0001F4C1", "파일함")  # 📁
        self._file_room_button.clicked.connect(self._on_transient_action(self.file_room_clicked))
        self._group.addButton(self._file_room_button)
        layout.addWidget(self._file_room_button)

        self._settings_button = _RailButton("⚙", "설정")  # ⚙
        self._settings_button.clicked.connect(self._on_transient_action(self.settings_clicked))
        self._group.addButton(self._settings_button)
        layout.addWidget(self._settings_button)

        layout.addStretch(1)

        self._my_avatar = AvatarWidget(36, initial="나", bg_color="#5B6472", parent=self)
        self._my_avatar.setCursor(Qt.PointingHandCursor)
        self._my_avatar.mousePressEvent = lambda event: self.settings_clicked.emit()
        avatar_row = QVBoxLayout()
        avatar_row.setAlignment(Qt.AlignHCenter)
        avatar_row.addWidget(self._my_avatar, alignment=Qt.AlignHCenter)
        layout.addLayout(avatar_row)

    def _on_transient_action(self, signal: Signal):
        """찾기/파일함/설정은 다이얼로그를 여는 일회성 동작이라, 눌렀다가 바로
        '채팅'으로 체크 상태를 되돌려 레일에는 항상 '채팅'만 활성으로 보이게 한다."""

        def handler(checked: bool) -> None:
            signal.emit()
            self._chat_button.setChecked(True)

        return handler

    @property
    def my_avatar(self) -> AvatarWidget:
        return self._my_avatar
