"""연락처(피어) 및 그룹 데이터 모델."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from dochat.config import PRESENCE_TIMEOUT_SEC


@dataclass
class Contact:
    id: str
    nickname: str
    ip: str
    port: int
    last_seen: float | None = None

    @property
    def online(self) -> bool:
        if self.last_seen is None:
            return False
        return (time.time() - self.last_seen) <= PRESENCE_TIMEOUT_SEC

    @property
    def address(self) -> tuple[str, int]:
        return (self.ip, self.port)


@dataclass
class Group:
    id: str
    name: str
    member_ids: list[str] = field(default_factory=list)
