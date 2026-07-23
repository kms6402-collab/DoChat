"""SQLite 기반 로컬 저장소: 연락처, 그룹, 메시지 히스토리, 파일 메타데이터."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from dochat.models.contact import Contact, Group
from dochat.models.message import FileRecord, Message

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    nickname TEXT NOT NULL,
    ip TEXT NOT NULL,
    port INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    PRIMARY KEY (group_id, contact_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    conversation_type TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    type TEXT NOT NULL,
    text TEXT,
    file_id TEXT,
    timestamp REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent',
    read_at REAL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, timestamp);

CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    local_path TEXT NOT NULL,
    status TEXT NOT NULL,
    timestamp REAL NOT NULL,
    conversation_id TEXT NOT NULL,
    direction TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """기존 DB(이전 버전에서 생성된)에 없는 컬럼을 보강한다."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(messages)").fetchall()}
        if "status" not in cols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'sent'")
        if "read_at" not in cols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN read_at REAL")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- contacts -----------------------------------------------------
    def add_contact(self, contact: Contact) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO contacts (id, nickname, ip, port) VALUES (?, ?, ?, ?)",
            (contact.id, contact.nickname, contact.ip, contact.port),
        )
        self._conn.commit()

    def get_contacts(self) -> list[Contact]:
        rows = self._conn.execute("SELECT * FROM contacts").fetchall()
        return [Contact(id=r["id"], nickname=r["nickname"], ip=r["ip"], port=r["port"]) for r in rows]

    def remove_contact(self, contact_id: str) -> None:
        self._conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        # 삭제된 연락처가 그룹 멤버로 유령처럼 남지 않도록 함께 정리한다.
        self._conn.execute("DELETE FROM group_members WHERE contact_id = ?", (contact_id,))
        self._conn.commit()

    # --- groups ---------------------------------------------------------
    def add_group(self, group: Group) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO groups (id, name) VALUES (?, ?)",
            (group.id, group.name),
        )
        self._conn.execute("DELETE FROM group_members WHERE group_id = ?", (group.id,))
        self._conn.executemany(
            "INSERT OR IGNORE INTO group_members (group_id, contact_id) VALUES (?, ?)",
            [(group.id, cid) for cid in group.member_ids],
        )
        self._conn.commit()

    def remove_group(self, group_id: str) -> None:
        self._conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        self._conn.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
        self._conn.commit()

    def get_groups(self) -> list[Group]:
        groups: dict[str, Group] = {}
        for r in self._conn.execute("SELECT * FROM groups").fetchall():
            groups[r["id"]] = Group(id=r["id"], name=r["name"], member_ids=[])
        for r in self._conn.execute("SELECT * FROM group_members").fetchall():
            if r["group_id"] in groups:
                groups[r["group_id"]].member_ids.append(r["contact_id"])
        return list(groups.values())

    # --- messages ---------------------------------------------------------
    def add_message(self, message: Message) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO messages
               (id, conversation_id, conversation_type, sender_id, type, text, file_id, timestamp, status, read_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message.id,
                message.conversation_id,
                message.conversation_type,
                message.sender_id,
                message.type,
                message.text,
                message.file_id,
                message.timestamp,
                message.status,
                message.read_at,
            ),
        )
        self._conn.commit()

    def get_messages(self, conversation_id: str) -> list[Message]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
            (conversation_id,),
        ).fetchall()
        return [
            Message(
                id=r["id"],
                conversation_id=r["conversation_id"],
                conversation_type=r["conversation_type"],
                sender_id=r["sender_id"],
                type=r["type"],
                text=r["text"],
                file_id=r["file_id"],
                timestamp=r["timestamp"],
                status=r["status"] if r["status"] is not None else "sent",
                read_at=r["read_at"],
            )
            for r in rows
        ]

    def get_pending_messages_for_contact(self, contact_id: str) -> list[Message]:
        """status='pending'이고 conversation_id가 해당 연락처(1:1 대화)인 메시지 목록."""
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? AND status = 'pending' ORDER BY timestamp ASC",
            (contact_id,),
        ).fetchall()
        return [
            Message(
                id=r["id"],
                conversation_id=r["conversation_id"],
                conversation_type=r["conversation_type"],
                sender_id=r["sender_id"],
                type=r["type"],
                text=r["text"],
                file_id=r["file_id"],
                timestamp=r["timestamp"],
                status=r["status"] if r["status"] is not None else "sent",
                read_at=r["read_at"],
            )
            for r in rows
        ]

    def get_all_pending_messages(self) -> list[Message]:
        """status='pending'인 모든 메시지 (재시작 시 재전송 큐 복원용)."""
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE status = 'pending' ORDER BY timestamp ASC",
        ).fetchall()
        return [
            Message(
                id=r["id"],
                conversation_id=r["conversation_id"],
                conversation_type=r["conversation_type"],
                sender_id=r["sender_id"],
                type=r["type"],
                text=r["text"],
                file_id=r["file_id"],
                timestamp=r["timestamp"],
                status=r["status"] if r["status"] is not None else "sent",
                read_at=r["read_at"],
            )
            for r in rows
        ]

    def mark_message_status(self, message_id: str, status: str) -> None:
        self._conn.execute("UPDATE messages SET status = ? WHERE id = ?", (status, message_id))
        self._conn.commit()

    def mark_message_read(self, message_id: str, read_at: float) -> None:
        self._conn.execute("UPDATE messages SET read_at = ? WHERE id = ?", (read_at, message_id))
        self._conn.commit()

    # --- settings (환경설정 key-value) ---------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if r is None:
            return default
        return r["value"]

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def get_last_message(self, conversation_id: str) -> Message | None:
        r = self._conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if r is None:
            return None
        return Message(
            id=r["id"],
            conversation_id=r["conversation_id"],
            conversation_type=r["conversation_type"],
            sender_id=r["sender_id"],
            type=r["type"],
            text=r["text"],
            file_id=r["file_id"],
            timestamp=r["timestamp"],
            status=r["status"] if r["status"] is not None else "sent",
            read_at=r["read_at"],
        )

    # --- files ---------------------------------------------------------
    def add_file_record(self, record: FileRecord) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO files
               (file_id, filename, size, mime_type, local_path, status, timestamp, conversation_id, direction)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.file_id,
                record.filename,
                record.size,
                record.mime_type,
                record.local_path,
                record.status,
                record.timestamp,
                record.conversation_id,
                record.direction,
            ),
        )
        self._conn.commit()

    def update_file_status(self, file_id: str, status: str) -> None:
        self._conn.execute("UPDATE files SET status = ? WHERE file_id = ?", (status, file_id))
        self._conn.commit()

    def get_file_record(self, file_id: str) -> FileRecord | None:
        r = self._conn.execute("SELECT * FROM files WHERE file_id = ?", (file_id,)).fetchone()
        if r is None:
            return None
        return FileRecord(
            file_id=r["file_id"],
            filename=r["filename"],
            size=r["size"],
            mime_type=r["mime_type"],
            local_path=r["local_path"],
            status=r["status"],
            timestamp=r["timestamp"],
            conversation_id=r["conversation_id"],
            direction=r["direction"],
        )

    def get_all_files(self) -> list[FileRecord]:
        rows = self._conn.execute("SELECT * FROM files ORDER BY timestamp DESC").fetchall()
        return [
            FileRecord(
                file_id=r["file_id"],
                filename=r["filename"],
                size=r["size"],
                mime_type=r["mime_type"],
                local_path=r["local_path"],
                status=r["status"],
                timestamp=r["timestamp"],
                conversation_id=r["conversation_id"],
                direction=r["direction"],
            )
            for r in rows
        ]
