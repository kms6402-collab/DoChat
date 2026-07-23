"""DoChat UDP 패킷 포맷 정의 및 직렬화/역직렬화.

모든 패킷은 JSON으로 직렬화한다. 파일 청크의 바이너리 데이터만 base64로 인코딩해
JSON 안에 포함시킨다. 성능이 문제가 되면 이후 바이너리 포맷으로 교체할 수 있다.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any


class MsgType:
    HELLO = "HELLO"
    PRESENCE = "PRESENCE"
    TEXT = "TEXT"
    GROUP_INVITE = "GROUP_INVITE"
    FILE_META = "FILE_META"
    FILE_CHUNK = "FILE_CHUNK"
    ACK = "ACK"

    # ACK가 필요 없는(응답을 기다리지 않는) 타입들
    NO_ACK_TYPES = frozenset({ACK, PRESENCE})


@dataclass
class Packet:
    msg_type: str
    seq: int
    sender_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    def needs_ack(self) -> bool:
        return self.msg_type not in MsgType.NO_ACK_TYPES

    def encode(self) -> bytes:
        return json.dumps(
            {
                "t": self.msg_type,
                "seq": self.seq,
                "from": self.sender_id,
                "payload": self.payload,
            },
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def decode(data: bytes) -> "Packet":
        obj = json.loads(data.decode("utf-8"))
        return Packet(
            msg_type=obj["t"],
            seq=obj["seq"],
            sender_id=obj["from"],
            payload=obj.get("payload", {}),
        )


def encode_file_chunk(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def decode_file_chunk(data_b64: str) -> bytes:
    return base64.b64decode(data_b64)
