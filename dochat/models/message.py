"""메시지 및 파일 전송 기록 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass


class ConversationType:
    DIRECT = "direct"
    GROUP = "group"


class MessageType:
    TEXT = "text"
    FILE = "file"


class FileStatus:
    SENDING = "sending"
    RECEIVING = "receiving"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Message:
    id: str
    conversation_id: str
    conversation_type: str  # ConversationType.DIRECT | GROUP
    sender_id: str
    type: str  # MessageType.TEXT | FILE
    timestamp: float
    text: str | None = None
    file_id: str | None = None
    status: str = "sent"  # "sent" | "pending" | "failed"
    read_at: float | None = None


@dataclass
class FileRecord:
    file_id: str
    filename: str
    size: int
    mime_type: str
    local_path: str
    status: str  # FileStatus.*
    timestamp: float
    conversation_id: str
    direction: str  # "in" | "out"
