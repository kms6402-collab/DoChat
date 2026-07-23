"""공유 비밀키 기반 UDP 페이로드 암호화. cryptography.fernet 사용."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def derive_key(passphrase: str) -> bytes:
    """passphrase로부터 Fernet이 요구하는 32바이트 base64 URL-safe 키를 만든다."""
    digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class PayloadCipher:
    def __init__(self, passphrase: str):
        self._fernet = Fernet(derive_key(passphrase))

    def encrypt(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt(self, data: bytes) -> bytes | None:
        """복호화 실패(다른 키를 쓰는 발신자 등) 시 예외 대신 None을 반환한다."""
        try:
            return self._fernet.decrypt(data)
        except InvalidToken:
            return None
