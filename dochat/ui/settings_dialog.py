"""환경설정(내 정보) 다이얼로그.

내 닉네임, 내 연결 정보(IP:포트), 파일 저장 폴더, 리스닝 포트, 새 메시지
알림음, 버전 정보 및 git 기반 업데이트 확인/적용을 한 화면에서 다룬다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImage
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dochat import autostart, config, update_checker
from dochat.models.storage import Storage
from dochat.network.chat_engine import ChatEngine
from dochat.ui import themes
from dochat.ui.avatar_widget import AvatarWidget

_DEFAULT_FONT_NAME = "Malgun Gothic"


def _process_avatar_image(source_path: str, dest_path: Path) -> bool:
    """이미지를 정사각형으로 중앙 크롭하고 축소한 뒤, AVATAR_MAX_BYTES 이하가 될
    때까지 JPEG 품질을 낮춰가며 dest_path에 저장한다. 성공하면 True."""
    image = QImage(source_path)
    if image.isNull():
        return False

    side = min(image.width(), image.height())
    x = (image.width() - side) // 2
    y = (image.height() - side) // 2
    cropped = image.copy(x, y, side, side)
    scaled = cropped.scaled(
        config.AVATAR_MAX_DIMENSION,
        config.AVATAR_MAX_DIMENSION,
        Qt.IgnoreAspectRatio,
        Qt.SmoothTransformation,
    )

    for quality in (85, 70, 55, 40, 25):
        if scaled.save(str(dest_path), "JPEG", quality) and dest_path.stat().st_size <= config.AVATAR_MAX_BYTES:
            return True
    return dest_path.exists()


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
        nickname_row = QHBoxLayout()
        nickname_reset_button = QPushButton("초기화")
        nickname_reset_button.setToolTip("닉네임과 프로필 사진을 기본값으로 되돌립니다 (저장을 눌러야 적용됩니다).")
        nickname_reset_button.clicked.connect(self._on_reset_profile)
        nickname_row.addWidget(self._nickname_edit, 1)
        nickname_row.addWidget(nickname_reset_button)
        form.addRow("내 닉네임", nickname_row)

        nickname_hint = QLabel(
            "닉네임은 상대방에게 그대로 보입니다. 개인정보(실명/사내 계정 등)가 "
            "포함되지 않도록 주의해 주세요."
        )
        nickname_hint.setObjectName("DialogHint")
        nickname_hint.setWordWrap(True)
        form.addRow("", nickname_hint)

        # --- 내 프로필 사진 ---------------------------------------------
        # "사진 변경/제거"는 다른 설정들과 마찬가지로 저장을 눌러야 실제
        # 반영된다(취소하면 원래 사진 그대로). _avatar_action으로 이번 세션에서
        # 무엇을 할지만 기억해두고, 실제 파일 반영/네트워크 전송은 _on_accept에서 한다.
        self._avatar_action: str = "keep"  # "keep" | "set" | "remove"
        self._avatar_staged_path: str | None = None

        avatar_row = QHBoxLayout()
        avatar_bg = themes.get_app_theme(storage).accent
        self._avatar_preview = AvatarWidget(
            56, initial=chat_engine.my_nickname, bg_color=avatar_bg, photo_path=None
        )
        avatar_change_button = QPushButton("사진 변경")
        avatar_change_button.clicked.connect(self._on_pick_avatar)
        avatar_remove_button = QPushButton("제거")
        avatar_remove_button.clicked.connect(self._on_remove_avatar)
        avatar_row.addWidget(self._avatar_preview)
        avatar_row.addWidget(avatar_change_button)
        avatar_row.addWidget(avatar_remove_button)
        avatar_row.addStretch(1)
        form.addRow("내 프로필 사진", avatar_row)

        avatar_hint = QLabel(
            "설정한 사진은 대화 상대에게도 전송되어 상대방 화면에도 표시됩니다."
        )
        avatar_hint.setObjectName("DialogHint")
        avatar_hint.setWordWrap(True)
        form.addRow("", avatar_hint)

        self._refresh_avatar_preview()
        self._nickname_edit.textChanged.connect(lambda text: self._avatar_preview.set_initial(text or "?"))

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

        # --- 채팅 테마 -----------------------------------------------------
        self._mine_color: str = storage.get_setting("bubble_mine_color", "") or ""
        self._other_color: str = storage.get_setting("bubble_other_color", "") or ""

        self._theme_combo = QComboBox()
        for key, theme in themes.THEMES.items():
            self._theme_combo.addItem(theme.name, key)
        current_theme_key = storage.get_setting("bubble_theme", themes.DEFAULT_THEME_KEY)
        theme_index = self._theme_combo.findData(current_theme_key)
        self._theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        self._theme_combo.currentIndexChanged.connect(lambda _: self._update_color_buttons())
        form.addRow("채팅 테마", self._theme_combo)

        color_row = QHBoxLayout()
        self._mine_color_button = QPushButton("내 말풍선 색")
        self._mine_color_button.clicked.connect(self._on_pick_mine_color)
        self._other_color_button = QPushButton("상대 말풍선 색")
        self._other_color_button.clicked.connect(self._on_pick_other_color)
        reset_color_button = QPushButton("기본값으로")
        reset_color_button.clicked.connect(self._on_reset_colors)
        color_row.addWidget(self._mine_color_button)
        color_row.addWidget(self._other_color_button)
        color_row.addWidget(reset_color_button)
        form.addRow("말풍선 색 커스텀", color_row)

        color_hint = QLabel("커스텀 색을 지정하면 선택한 테마보다 우선 적용됩니다.")
        color_hint.setObjectName("DialogHint")
        color_hint.setWordWrap(True)
        form.addRow("", color_hint)

        # --- 실시간 미리보기 -------------------------------------------
        # 테마/색을 바꿀 때마다 실제 말풍선처럼 생긴 라벨을 즉시 갱신해서
        # 저장 후 대화창을 열어보지 않아도 결과를 바로 확인할 수 있게 한다.
        preview_frame = QFrame()
        preview_frame.setObjectName("ThemePreviewFrame")
        preview_frame.setFrameShape(QFrame.StyledPanel)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setSpacing(6)
        preview_layout.setContentsMargins(10, 10, 10, 10)

        other_row = QHBoxLayout()
        self._preview_other_label = QLabel("상대방: 네, 반갑습니다")
        self._preview_other_label.setWordWrap(True)
        other_row.addWidget(self._preview_other_label)
        other_row.addStretch(1)
        preview_layout.addLayout(other_row)

        mine_row = QHBoxLayout()
        self._preview_mine_label = QLabel("나: 안녕하세요!")
        self._preview_mine_label.setWordWrap(True)
        mine_row.addStretch(1)
        mine_row.addWidget(self._preview_mine_label)
        preview_layout.addLayout(mine_row)

        form.addRow("미리보기", preview_frame)

        self._update_color_buttons()

        # --- 폰트 -----------------------------------------------------------
        # 앱 전체(사이드바/대화 목록/버튼 등 QSS 적용 위젯)의 글꼴/글자 크기를
        # 사용자가 직접 고를 수 있게 한다. 말풍선 안의 텍스트(message_bubble.py)는
        # QSS 밖에서 인라인 스타일로 그려지므로 이 설정의 영향을 받지 않는다.
        font_row = QHBoxLayout()
        self._font_combo = QFontComboBox()
        saved_font_family = storage.get_setting("app_font_family") or _DEFAULT_FONT_NAME
        self._font_combo.setCurrentFont(QFont(saved_font_family))
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(10, 20)
        self._font_size_spin.setSuffix("px")
        saved_font_size = storage.get_setting("app_font_size")
        self._font_size_spin.setValue(int(saved_font_size) if saved_font_size else 13)
        font_row.addWidget(self._font_combo, 1)
        font_row.addWidget(self._font_size_spin)
        form.addRow("폰트", font_row)

        font_hint = QLabel("앱 전체(메뉴/목록/버튼 등)의 글꼴과 글자 크기입니다. 저장 후 즉시 반영됩니다.")
        font_hint.setObjectName("DialogHint")
        font_hint.setWordWrap(True)
        form.addRow("", font_hint)

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

        # --- 트레이 알림 -----------------------------------------------
        self._notify_popup_check = QCheckBox("트레이 알림 표시 (창이 숨겨져 있을 때 새 메시지를 풍선 알림으로 표시)")
        notify_popup_default = storage.get_setting("notify_popup", "1") == "1"
        self._notify_popup_check.setChecked(notify_popup_default)
        form.addRow("", self._notify_popup_check)

        # --- 자동 시작 -----------------------------------------------------
        self._autostart_check = QCheckBox("Windows 시작 시 자동 실행")
        self._autostart_check.setChecked(autostart.is_enabled())
        self._autostart_check.setEnabled(autostart.is_supported())
        if not autostart.is_supported():
            self._autostart_check.setToolTip("패키지된 Windows 실행 파일에서만 사용할 수 있습니다.")
        form.addRow("", self._autostart_check)

        # --- 네트워크 진단 ---------------------------------------------
        diagnostic_row = QHBoxLayout()
        diagnostic_hint = QLabel("연결 문제가 있을 때 상대방 IP:포트로 도달 가능한지 확인합니다.")
        diagnostic_hint.setObjectName("DialogHint")
        diagnostic_hint.setWordWrap(True)
        self._diagnostic_button = QPushButton("🔌 네트워크 진단")
        self._diagnostic_button.clicked.connect(self._on_open_network_diagnostic)
        diagnostic_row.addWidget(diagnostic_hint, 1)
        diagnostic_row.addWidget(self._diagnostic_button)
        root.addLayout(diagnostic_row)

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
    def _current_theme_key(self) -> str:
        key = self._theme_combo.currentData()
        return key if key else themes.DEFAULT_THEME_KEY

    def _update_color_buttons(self) -> None:
        """색상 버튼 배경을 현재 지정된 색(커스텀 우선, 없으면 테마 색)으로 갱신한다."""
        theme = themes.THEMES.get(self._current_theme_key(), themes.THEMES[themes.DEFAULT_THEME_KEY])
        mine_color = self._mine_color or theme.mine_bg
        other_color = self._other_color or theme.other_bg
        self._mine_color_button.setStyleSheet(
            f"background-color: {mine_color}; color: {theme.mine_text};"
        )
        self._other_color_button.setStyleSheet(
            f"background-color: {other_color}; color: {theme.other_text};"
        )

        # 실제 말풍선처럼 생긴 미리보기 라벨도 함께 갱신한다.
        self._preview_mine_label.setStyleSheet(
            f"background-color: {mine_color}; color: {theme.mine_text}; "
            "border-radius: 12px; padding: 8px 12px;"
        )
        self._preview_other_label.setStyleSheet(
            f"background-color: {other_color}; color: {theme.other_text}; "
            "border-radius: 12px; padding: 8px 12px;"
        )

    def _on_pick_mine_color(self) -> None:
        initial = QColor(self._mine_color) if self._mine_color else QColor(
            themes.THEMES[self._current_theme_key()].mine_bg
        )
        color = QColorDialog.getColor(initial, self, "내 말풍선 색 선택")
        if color.isValid():
            self._mine_color = color.name()
            self._update_color_buttons()

    def _on_pick_other_color(self) -> None:
        initial = QColor(self._other_color) if self._other_color else QColor(
            themes.THEMES[self._current_theme_key()].other_bg
        )
        color = QColorDialog.getColor(initial, self, "상대 말풍선 색 선택")
        if color.isValid():
            self._other_color = color.name()
            self._update_color_buttons()

    def _on_reset_profile(self) -> None:
        """닉네임/프로필 사진을 기본값으로 되돌린다(저장을 눌러야 실제 반영)."""
        self._nickname_edit.setText("새 사용자")
        self._avatar_action = "remove"
        self._avatar_staged_path = None
        self._refresh_avatar_preview()

    def _on_pick_avatar(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "프로필 사진 선택", "", "이미지 파일 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not path:
            return

        staged_path = config.APP_DIR / "avatar_staged.jpg"
        if not _process_avatar_image(path, staged_path):
            QMessageBox.warning(self, "사진 불러오기 실패", "선택한 이미지를 불러올 수 없습니다.")
            return

        self._avatar_action = "set"
        self._avatar_staged_path = str(staged_path)
        self._refresh_avatar_preview()

    def _on_remove_avatar(self) -> None:
        self._avatar_action = "remove"
        self._avatar_staged_path = None
        self._refresh_avatar_preview()

    def _refresh_avatar_preview(self) -> None:
        """현재 스테이징 상태(변경/제거/유지)에 맞는 사진을 미리보기에 반영한다."""
        if self._avatar_action == "set":
            photo_path = self._avatar_staged_path
        elif self._avatar_action == "remove":
            photo_path = None
        else:
            photo_path = str(config.MY_AVATAR_PATH) if config.MY_AVATAR_PATH.exists() else None
        self._avatar_preview.set_initial(self._nickname_edit.text() or "?")
        self._avatar_preview.set_photo_path(photo_path)

    def _on_reset_colors(self) -> None:
        self._mine_color = ""
        self._other_color = ""
        self._update_color_buttons()

    # ------------------------------------------------------------------
    def _on_open_network_diagnostic(self) -> None:
        from dochat.ui.network_diagnostic_dialog import NetworkDiagnosticDialog  # 순환참조 방지를 위한 지연 import

        NetworkDiagnosticDialog(self._chat_engine, parent=self).exec()

    # ------------------------------------------------------------------
    def _on_check_update(self) -> None:
        if not update_checker.is_git_checkout():
            from dochat import self_updater

            if self_updater.is_supported():
                self._on_check_self_update(self_updater)
            else:
                self._on_check_update_via_browser()
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
    def _on_check_self_update(self, self_updater) -> None:
        """Windows 단일 파일(exe) 배포본: 새 버전을 내려받아 자동으로 교체·재시작한다."""
        self._update_button.setEnabled(False)
        self._update_button.setText("확인 중...")
        QApplication.processEvents()
        try:
            result = self_updater.check_for_self_update()
        finally:
            self._update_button.setEnabled(True)
            self._update_button.setText("업데이트 확인")

        if result.get("error"):
            QMessageBox.warning(self, "업데이트 확인 실패", result["error"])
            return

        if not result.get("has_update"):
            QMessageBox.information(self, "업데이트 확인", "최신 버전입니다.")
            return

        answer = QMessageBox.question(
            self,
            "업데이트 확인",
            f"새 버전이 있습니다 ({result['remote_tag']}).\n"
            "지금 다운로드해서 자동으로 업데이트할까요? 완료되면 DoChat이 자동으로 재시작됩니다.",
        )
        if answer != QMessageBox.Yes:
            return

        self._update_button.setEnabled(False)
        self._update_button.setText("다운로드 중...")
        QApplication.processEvents()
        success, message = self_updater.apply_self_update(
            result["download_url"], expected_size=result.get("size")
        )

        if success:
            QMessageBox.information(self, "업데이트", message)
            QApplication.quit()
        else:
            self._update_button.setEnabled(True)
            self._update_button.setText("업데이트 확인")
            QMessageBox.warning(self, "업데이트 실패", message)

    def _on_check_update_via_browser(self) -> None:
        """자동 업데이트를 지원하지 않는 배포본(예: macOS .pkg): 릴리스 페이지 안내만 표시."""
        from dochat import release_checker

        self._update_button.setEnabled(False)
        self._update_button.setText("확인 중...")
        QApplication.processEvents()
        try:
            result = release_checker.check_for_new_release()
        finally:
            self._update_button.setEnabled(True)
            self._update_button.setText("업데이트 확인")

        if result.get("error"):
            QMessageBox.warning(self, "업데이트 확인 실패", result["error"])
            return

        if not result.get("has_update"):
            QMessageBox.information(self, "업데이트 확인", "최신 버전입니다.")
            return

        answer = QMessageBox.question(
            self,
            "업데이트 확인",
            f"새 버전이 있습니다 (최신 커밋: {result['remote_short']}).\n"
            "GitHub 릴리스/빌드 페이지에서 최신 실행 파일을 받으시겠습니까?",
        )
        if answer == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl(release_checker.releases_page_url()))

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
        self._storage.set_setting("notify_popup", "1" if self._notify_popup_check.isChecked() else "0")

        self._storage.set_setting("bubble_theme", self._current_theme_key())
        self._storage.set_setting("bubble_mine_color", self._mine_color)
        self._storage.set_setting("bubble_other_color", self._other_color)

        if autostart.is_supported():
            success, message = autostart.set_enabled(self._autostart_check.isChecked())
            if not success:
                QMessageBox.warning(self, "자동 시작 설정 실패", message)

        self._storage.set_setting("app_font_family", self._font_combo.currentFont().family())
        self._storage.set_setting("app_font_size", str(self._font_size_spin.value()))

        if self._avatar_action == "set" and self._avatar_staged_path:
            shutil.copyfile(self._avatar_staged_path, config.MY_AVATAR_PATH)
            self._chat_engine.broadcast_my_avatar()
        elif self._avatar_action == "remove":
            config.MY_AVATAR_PATH.unlink(missing_ok=True)
            # 상대방에게 이미 전달된 사진 캐시까지 지울 방법은 없지만(전송
            # 프로토콜이 "삭제" 메시지를 지원하지 않음), 적어도 내 쪽 파일은
            # 지워 다음 번 사진 등록 전까지 더 이상 전송되지 않게 한다.

        self.accept()
