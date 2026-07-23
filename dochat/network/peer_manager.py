"""연락처(피어) 목록과 온라인 상태(프레즌스)를 관리한다."""
from __future__ import annotations

import time
import uuid

from dochat.models.contact import Contact
from dochat.models.storage import Storage


class PeerManager:
    """알고 있는 연락처들과 그들의 마지막 프레즌스 시각을 관리한다."""

    def __init__(self, storage: Storage):
        self.storage = storage
        self.contacts: dict[str, Contact] = {}
        for contact in storage.get_contacts():
            self.contacts[contact.id] = contact

    def add_contact(self, nickname: str, ip: str, port: int) -> Contact:
        contact = Contact(id=str(uuid.uuid4()), nickname=nickname, ip=ip, port=port)
        self.storage.add_contact(contact)
        self.contacts[contact.id] = contact
        return contact

    def get_contact(self, contact_id: str) -> Contact | None:
        return self.contacts.get(contact_id)

    def update_contact(self, contact_id: str, nickname: str, ip: str, port: int) -> Contact | None:
        contact = self.contacts.get(contact_id)
        if contact is None:
            return None
        contact.nickname = nickname
        contact.ip = ip
        contact.port = port
        self.storage.add_contact(contact)
        self.contacts[contact_id] = contact
        return contact

    def remove_contact(self, contact_id: str) -> None:
        self.contacts.pop(contact_id, None)
        self.storage.remove_contact(contact_id)

    def mark_online(self, contact_id: str) -> None:
        contact = self.contacts.get(contact_id)
        if contact is None:
            return
        contact.last_seen = time.time()

    def all_contacts(self) -> list[Contact]:
        return list(self.contacts.values())
