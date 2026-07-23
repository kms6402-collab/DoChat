"""환경설정(내 정보) 다이얼로그.

내 닉네임, 내 연결 정보(IP:포트), 파일 저장 폴더, 리스닝 포트, 새 메시지
알림음, 버전 정보 및 git 기반 업데이트 확인/적용을 한 화면에서 다룬다.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dochat import config, update_checker
from dochat.models.storage import Storage
from dochat.network.chat_engine import ChatEngine


class SettingsDialog(QDialog):
    """환경설정(내 정보) 다이얼로그."""

    def __init__(self, chat_engine: ChatEngine, storage: Storage, parent: QWidget | None = None):
        super().__init__(parent)
        self._chat_engine = chat_engine
        self._storage = storage

        self.setWindowTitle("환경설정")
        self.setModal(True)
        self.setMinimumWidth(560)

        self._selected_folder: str = str(config.RECEIVED_FILES_DIR)

        root = QVBoxLayout(self)
        root.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        root.addLayout(form)

        # --- 내 닉네임 -----------------------------------------------
        # 표시 이름이라 아주 길 필요는 없지만, 기존 필드가 시각적으로 너무
        # 좁아 보인다는 피드백에 따라 최소 폭을 넉넉히 확보하고 입력 가능
        # 글자 수도 여유 있게(40자) 늘렸다.
        self._nickname_edit = QLineEdit(chat_engine.my_nickname)
        self._nickname_edit.setPlaceholderText("예: 김철수")
        self._nickname_edit.setMaxLength(40)
        self._nickname_edit.setMinimumWidth(360)
        form.addRow("내 닉네임", self._nickname_edit)

        # --- 내 연결 정보 ----------------------------------------------
        ip, port = chat_engine.my_local_address
        address_row = QHBoxLayout()
        self._address_edit = QLineEdit(f"{ip}:{port}")
        self._address_edit.setReadOnly(True)
        copy_button = QPushButton("복사")
        copy_button.clicked.connect(self._on_copy_address)
        address_row.addWidget(self._address_edit, 1)
        address_row.addWidget(copy_button)
        form.addRow("내 연결 정보", address_row)

        address_hint = QLabel("다른 사람이 '새 대화 추가'에서 나를 등록할 때 입력할 IP:포트입니다.")
        address_hint.setObjectName("DialogHint")
        address_hint.setWordWrap(True)
        form.addRow("", address_hint)

        # --- 파일 저장 폴더 ---------------------------------------------
        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit(self._selected_folder)
        self._folder_edit.setReadOnly(True)
        browse_button = QPushButton("찾아보기")
        browse_button.clicked.connect(self._on_browse_folder)
        open_button = QPushButton("폴더 열기")
        open_button.clicked.connect(self._on_open_folder)
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(browse_button)
        folder_row.addWidget(open_button)
        form.addRow("파일 저장 폴더", folder_row)

        # --- 리스닝 포트 -------------------------------------------------
        current_port = getattr(chat_engine.socket.socket, "localPort", lambda: None)()
        if not current_port:
            current_port = config.DEFAULT_LISTEN_PORT
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(current_port)
        form.addRow("리스닝 포트", self._port_spin)

        port_hint = QLabel("이 값을 바꾸면 앱을 재시작해야 적용됩니다.")
        port_hint.setObjectName("DialogHint")
        form.addRow("", port_hint)

        # --- 보안 키(암호화) -----------------------------------------------
        self._network_key_edit = QLineEdit(storage.get_setting("network_key", "") or "")
        self._network_key_edit.setEchoMode(QLineEdit.Password)
        self._network_key_edit.setPlaceholderText("기본 키 사용")
        form.addRow("보안 키(암호화)", self._network_key_edit)

        network_key_hint = QLabel(
            "모든 참가자가 동일한 키를 입력해야 서로 통신할 수 있습니다. "
            "비워두면 기본 키를 사용합니다."
        )
        network_key_hint.setObjectName("DialogHint")
        network_key_hint.setWordWrap(True)
        form.addRow("", network_key_hint)

        # --- 알림음 -------------------------------------------------------
        self._notify_check = QCheckBox("새 메시지 도착 시 알림음")
        notify_default = storage.get_setting("notify_sound", "1") == "1"
        self._notify_check.setChecked(notify_default)
        form.addRow("", self._notify_check)

        # --- 버전 정보 / 업데이트 -----------------------------------------
        version_row = QHBoxLayout()
        version_label = QLabel(f"버전: {config.get_version_string()}")
        version_label.setObjectName("DialogHint")
        self._update_button = QPushButton("업데이트 확인")
        self._update_button.clicked.connect(self._on_check_update)
        version_row.addWidget(version_label)
        version_row.addStretch(1)
        version_row.addWidget(self._update_button)
        root.addLayout(version_row)

        # --- 저장/취소 -----------------------------------------------------
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("PrimaryButton")
        buttons.button(QDialogButtonBox.Ok).setText("저장")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    def _on_copy_address(self) -> None:
        QApplication.clipboard().setText(self._address_edit.text())

    def _on_browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "파일 저장 폴더 선택", self._selected_folder)
        if path:
            self._selected_folder = path
            self._folder_edit.setText(path)

    def _on_open_folder(self) -> None:
        path = self._selected_folder or str(config.RECEIVED_FILES_DIR)
        Path(path).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------
    def _on_check_update(self) -> None:
        if not update_checker.is_git_checkout():
            QMessageBox.information(
                self,
                "업데이트 확인",
                "패키지된 실행 파일에서는 자동 업데이트를 지원하지 않습니다.\n"
                "GitHub 릴리스 페이지에서 최신 버전을 받아주세요.",
            )
            return

        self._update_button.setEnabled(False)
        self._update_button.setText("확인 중...")
        QApplication.processEvents()
        try:
            result = update_checker.check_for_updates()
        finally:
            self._update_button.setEnabled(True)
            self._update_button.setText("업데이트 확인")

        if result.get("error"):
            QMessageBox.warning(self, "업데이트 확인 실패", result["error"])
            return

        if not result.get("has_update"):
            QMessageBox.information(self, "업데이트 확인", "최신 버전입니다.")
            return

        behind_count = result.get("behind_count", 0)
        answer = QMessageBox.question(
            self,
            "업데이트 확인",
            f"새 버전이 있습니다 ({behind_count}개 커밋 차이). 지금 업데이트할까요?",
        )
        if answer != QMessageBox.Yes:
            return

        self._update_button.setEnabled(False)
        self._update_button.setText("업데이트 중...")
        QApplication.processEvents()
        try:
            success, message = update_checker.apply_update()
        finally:
            self._update_button.setEnabled(True)
            self._update_button.setText("업데이트 확인")

        if success:
            QMessageBox.information(self, "업데이트 완료", message)
        else:
            QMessageBox.warning(self, "업데이트 실패", message)

    # ------------------------------------------------------------------
    def _on_accept(self) -> None:
        nickname = self._nickname_edit.text().strip()
        if not nickname:
            QMessageBox.warning(self, "입력 오류", "닉네임을 입력해 주세요.")
            return

        self._chat_engine.set_my_nickname(nickname)

        new_folder = self._selected_folder.strip()
        if new_folder:
            folder_path = Path(new_folder)
            folder_path.mkdir(parents=True, exist_ok=True)
            self._storage.set_setting("save_folder", str(folder_path))
            config.RECEIVED_FILES_DIR = folder_path

        self._storage.set_setting("listen_port", str(self._port_spin.value()))
        self._storage.set_setting("notify_sound", "1" if self._notify_check.isChecked() else "0")
        self._storage.set_setting("network_key", self._network_key_edit.text())

        self.accept()
