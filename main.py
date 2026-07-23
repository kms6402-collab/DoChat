"""DoChat 앱 진입점."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from dochat.ui.main_window import MainWindow


def resource_path(relative: str) -> Path:
    """리소스 파일의 절대 경로를 반환한다.

    개발 환경에서는 이 파일 기준 상대 경로를, PyInstaller로 패키징된
    실행 파일에서는 번들 임시 폴더(sys._MEIPASS) 기준 경로를 사용한다.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DoChat")
    app.setWindowIcon(QIcon(str(resource_path("assets/icon.png"))))
    # 창을 닫아도(트레이로 최소화) 앱 프로세스가 종료되지 않도록 한다.
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
