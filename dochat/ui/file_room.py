"""파일함 / 전송 히스토리 화면.

지금까지 주고받은 모든 파일(진행 중/완료/실패)을 한눈에 보여주고,
더블클릭으로 열거나 파일이 저장된 폴더를 바로 열 수 있게 한다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dochat.models.contact import Contact, Group
from dochat.models.message import ConversationType, FileStatus

_STATUS_LABEL = {
    FileStatus.SENDING: "전송 중",
    FileStatus.RECEIVING: "수신 중",
    FileStatus.COMPLETED: "완료",
    FileStatus.FAILED: "실패",
}
_DIRECTION_LABEL = {"out": "보냄", "in": "받음"}

_FILTER_ALL = "전체"
_FILTER_SENT = "보낸 파일"
_FILTER_RECEIVED = "받은 파일"
_FILTER_IN_PROGRESS = "전송 중"
_FILTER_FAILED = "실패"


def _human_size(size: int) -> str:
    n = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _format_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _reveal_in_file_manager(path: str) -> None:
    """OS 파일 탐색기에서 해당 파일이 있는 폴더를 열고 파일을 선택 표시한다."""
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", path], check=False)
    elif sys.platform.startswith("win"):
        subprocess.run(["explorer", "/select,", path], check=False)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


class FileRoomDialog(QDialog):
    """파일함/전송 히스토리 화면. 메인 윈도우에서 비모달로 띄운다."""

    def __init__(self, chat_engine, storage, parent: QWidget | None = None):
        super().__init__(parent)
        self._chat_engine = chat_engine
        self._storage = storage

        self.setWindowTitle("파일함")
        self.resize(760, 480)
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("파일함")
        title.setObjectName("DialogLabel")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        header_row.addWidget(title)
        header_row.addStretch(1)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(
            [_FILTER_ALL, _FILTER_SENT, _FILTER_RECEIVED, _FILTER_IN_PROGRESS, _FILTER_FAILED]
        )
        self._filter_combo.currentTextChanged.connect(lambda _: self.refresh())
        header_row.addWidget(self._filter_combo)

        refresh_button = QPushButton("새로고침")
        refresh_button.clicked.connect(self.refresh)
        header_row.addWidget(refresh_button)

        layout.addLayout(header_row)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["파일명", "대화상대", "방향", "용량", "상태", "받은 시간"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self._table, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._open_button = QPushButton("열기")
        self._open_button.clicked.connect(self._open_selected)
        self._reveal_button = QPushButton("폴더에서 보기")
        self._reveal_button.clicked.connect(self._reveal_selected)
        button_row.addWidget(self._open_button)
        button_row.addWidget(self._reveal_button)
        layout.addLayout(button_row)

        self._empty_label = QLabel("아직 주고받은 파일이 없습니다.")
        self._empty_label.setObjectName("DialogHint")
        self._empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._empty_label)

        self._conversation_name_cache: dict[str, str] = {}

        self.refresh()

    # ------------------------------------------------------------------
    def _conversation_name(self, conversation_id: str) -> str:
        if conversation_id in self._conversation_name_cache:
            return self._conversation_name_cache[conversation_id]

        name = conversation_id
        contact: Contact | None = self._chat_engine.get_contact(conversation_id)
        if contact is not None:
            name = contact.nickname
        else:
            for group in self._chat_engine.get_groups():
                group: Group
                if group.id == conversation_id:
                    name = f"[그룹] {group.name}"
                    break

        self._conversation_name_cache[conversation_id] = name
        return name

    def _matches_filter(self, record) -> bool:
        current = self._filter_combo.currentText()
        if current == _FILTER_ALL:
            return True
        if current == _FILTER_SENT:
            return record.direction == "out"
        if current == _FILTER_RECEIVED:
            return record.direction == "in"
        if current == _FILTER_IN_PROGRESS:
            return record.status in (FileStatus.SENDING, FileStatus.RECEIVING)
        if current == _FILTER_FAILED:
            return record.status == FileStatus.FAILED
        return True

    def refresh(self) -> None:
        """storage에서 파일 목록을 다시 읽어 표를 갱신한다."""
        self._conversation_name_cache.clear()
        records = [r for r in self._storage.get_all_files() if self._matches_filter(r)]

        self._table.setRowCount(len(records))
        for row, record in enumerate(records):
            self._table.setItem(row, 0, QTableWidgetItem(record.filename))
            self._table.setItem(row, 1, QTableWidgetItem(self._conversation_name(record.conversation_id)))
            self._table.setItem(row, 2, QTableWidgetItem(_DIRECTION_LABEL.get(record.direction, record.direction)))
            self._table.setItem(row, 3, QTableWidgetItem(_human_size(record.size)))
            self._table.setItem(row, 4, QTableWidgetItem(_STATUS_LABEL.get(record.status, record.status)))
            self._table.setItem(row, 5, QTableWidgetItem(_format_time(record.timestamp)))
            for col in range(6):
                item = self._table.item(row, col)
                item.setData(Qt.UserRole, record)

        self._empty_label.setVisible(len(records) == 0)
        self._table.setVisible(len(records) > 0)

    # ------------------------------------------------------------------
    def _selected_record(self):
        items = self._table.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.UserRole)

    def _on_row_double_clicked(self, index) -> None:
        self._open_selected()

    def _open_selected(self) -> None:
        record = self._selected_record()
        if record is None or not record.local_path or not os.path.exists(record.local_path):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(record.local_path))

    def _reveal_selected(self) -> None:
        record = self._selected_record()
        if record is None or not record.local_path or not os.path.exists(record.local_path):
            return
        _reveal_in_file_manager(record.local_path)
