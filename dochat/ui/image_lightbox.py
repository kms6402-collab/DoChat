"""이미지 파일 클릭 시 확대해서 보여주는 간단한 라이트박스 다이얼로그."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget


class ImageLightboxDialog(QDialog):
    """이미지 썸네일을 클릭했을 때 원본(또는 화면에 맞게 축소한) 이미지를 크게 보여준다.

    ESC 키(QDialog 기본 동작) 또는 이미지 클릭으로 닫을 수 있다.
    """

    def __init__(self, image_path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("이미지 보기")
        self.setModal(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        pixmap = QPixmap(image_path)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        if not pixmap.isNull():
            # 화면(또는 적당한 최대 크기, 예: 1000x800)을 넘지 않게 축소해서 표시
            max_w, max_h = 1000, 800
            if pixmap.width() > max_w or pixmap.height() > max_h:
                pixmap = pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pixmap)
            label.setCursor(Qt.PointingHandCursor)
            label.mousePressEvent = lambda event: self.close()
            self.resize(pixmap.width(), pixmap.height() + 20)
        else:
            label.setText("이미지를 불러올 수 없습니다.")
        layout.addWidget(label)
