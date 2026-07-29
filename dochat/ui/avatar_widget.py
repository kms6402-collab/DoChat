"""사진 또는 색상+이니셜로 그려지는 공용 원형 아바타 위젯.

프로필 사진이 설정돼 있으면(로컬 파일이 존재하고 로드에 성공하면) 원형으로
잘라 그리고, 없으면 배경색 원 + 이니셜 한 글자로 폴백한다. conversation_list.py
(대화 목록)와 message_bubble.py(메시지 헤더)가 함께 사용한다.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

# 연락처마다 다른 색을 배정해(참고 디자인처럼 다채로운 아바타 팔레트) 목록/메시지
# 헤더 어디서든 같은 사람은 항상 같은 색으로 보이게 한다(id 해시 기반, 안정적).
_AVATAR_PALETTE = [
    "#EE9C5D",  # 코랄오렌지
    "#6FBF8B",  # 그린
    "#6FA8DC",  # 블루
    "#B18CD9",  # 바이올렛
    "#E07A9E",  # 핑크
    "#5FBFBF",  # 틸
    "#D6B35C",  # 머스타드
]
GROUP_AVATAR_COLOR = "#D97706"
ME_AVATAR_COLOR = "#9AA1AC"


def avatar_color_for(identifier: str) -> str:
    """id 문자열을 해시해 팔레트에서 안정적으로 색 하나를 골라 반환한다."""
    if not identifier:
        return _AVATAR_PALETTE[0]
    index = sum(identifier.encode("utf-8")) % len(_AVATAR_PALETTE)
    return _AVATAR_PALETTE[index]


class AvatarWidget(QWidget):
    def __init__(
        self,
        size: int,
        initial: str = "?",
        bg_color: str = "#5B6472",
        photo_path: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._size = size
        self._initial = (initial[:1] or "?").upper()
        self._bg_color = QColor(bg_color)
        self._pixmap: QPixmap | None = None
        self.setFixedSize(size, size)
        self.set_photo_path(photo_path)

    def set_photo_path(self, photo_path: str | None) -> None:
        """사진 경로를 갱신한다. 없거나 로드에 실패하면 이니셜 폴백으로 되돌린다."""
        pixmap = None
        if photo_path and Path(photo_path).exists():
            candidate = QPixmap(photo_path)
            if not candidate.isNull():
                pixmap = candidate
        self._pixmap = pixmap
        self.update()

    def set_initial(self, initial: str) -> None:
        self._initial = (initial[:1] or "?").upper()
        self.update()

    def set_bg_color(self, bg_color: str) -> None:
        self._bg_color = QColor(bg_color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: D401 - Qt 콜백
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        clip_path = QPainterPath()
        clip_path.addEllipse(QRectF(0, 0, self._size, self._size))
        painter.setClipPath(clip_path)

        if self._pixmap is not None:
            # KeepAspectRatioByExpanding: 정사각형을 꽉 채우도록 확대한 뒤
            # 중앙을 기준으로 잘라내(원형 클립은 위에서 이미 걸려 있음) 사진이
            # 찌그러지지 않게 한다.
            scaled = self._pixmap.scaled(
                self._size,
                self._size,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = (scaled.width() - self._size) // 2
            y = (scaled.height() - self._size) // 2
            painter.drawPixmap(-x, -y, scaled)
        else:
            painter.fillRect(0, 0, self._size, self._size, self._bg_color)
            painter.setPen(QColor("#FFFFFF"))
            font = QFont(self.font())
            font.setPixelSize(max(10, int(self._size * 0.42)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(0, 0, self._size, self._size), Qt.AlignCenter, self._initial)
