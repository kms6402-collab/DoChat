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
    timestamp REAL NOT NULL
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
"""


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
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
               (id, conversation_id, conversation_type, sender_id, type, text, file_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message.id,
                message.conversation_id,
                message.conversation_type,
                message.sender_id,
                message.type,
                message.text,
                message.file_id,
                message.timestamp,
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
            )
            for r in rows
        ]

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
