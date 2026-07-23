"""LAN 자동 탐색: UDP 브로드캐스트로 같은 네트워크의 DoChat 사용자를 찾는다.

`dochat/network/chat_engine.py`, `protocol.py`, `reliable_udp.py`와는
완전히 독립된 모듈이다. 실패해도(방화벽 등으로 브로드캐스트가 막힌 경우 등)
채팅 본 기능에 영향을 주지 않도록 모든 예외를 조용히 삼킨다.
"""
from __future__ import annotations

import json
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QUdpSocket

ANNOUNCE_TYPE = "DOCHAT_ANNOUNCE"
DEFAULT_DISCOVERY_PORT = 47476
ANNOUNCE_INTERVAL_MS = 3000
PEER_TTL_SEC = 30.0


class LanDiscovery(QObject):
    """UDP 브로드캐스트로 같은 LAN의 다른 DoChat 인스턴스를 주기적으로 알리고 수신한다."""

    # client_id, nickname, ip, chat_port
    peer_discovered = Signal(str, str, str, int)

    def __init__(
        self,
        client_id: str,
        get_nickname: Callable[[], str],
        chat_port: int,
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        parent=None,
    ):
        super().__init__(parent)
        self._client_id = client_id
        self._get_nickname = get_nickname
        self._chat_port = chat_port
        self._discovery_port = discovery_port

        self._discovered: dict[str, dict] = {}
        self._enabled = False

        self._socket = QUdpSocket(self)
        self._timer = QTimer(self)
        self._timer.setInterval(ANNOUNCE_INTERVAL_MS)
        self._timer.timeout.connect(self._broadcast_announce)

        try:
            bound = self._socket.bind(
                QHostAddress.AnyIPv4,
                self._discovery_port,
                QUdpSocket.ShareAddress | QUdpSocket.ReuseAddressHint,
            )
        except Exception:
            bound = False

        if bound:
            # Qt5에서는 브로드캐스트 송신을 위해 이 옵션이 필요했지만, Qt6에서는
            # 해당 열거값 자체가 제거되었고 UDP 소켓이 기본적으로 브로드캐스트를
            # 허용한다. 존재하는 경우에만 설정하고, 없거나 실패해도 무시한다
            # (브로드캐스트 자체는 옵션 없이도 동작함을 확인함).
            try:
                broadcast_opt = getattr(QAbstractSocket, "BroadcastOptionEnabled", None) or getattr(
                    getattr(QAbstractSocket, "SocketOption", None), "BroadcastOptionEnabled", None
                )
                if broadcast_opt is not None:
                    self._socket.setSocketOption(broadcast_opt, True)
            except Exception:
                pass

            try:
                self._socket.readyRead.connect(self._on_ready_read)
                self._enabled = True
            except Exception:
                self._enabled = False

    def start(self) -> None:
        """탐색을 시작한다. 소켓 바인딩에 실패했다면 조용히 아무 것도 하지 않는다."""
        if not self._enabled:
            return
        try:
            self._broadcast_announce()
            self._timer.start()
        except Exception:
            pass

    def stop(self) -> None:
        """탐색을 중지하고 소켓을 닫는다."""
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            self._socket.close()
        except Exception:
            pass
        self._enabled = False

    def discovered_peers(self) -> list[dict]:
        """최근 PEER_TTL_SEC초 이내에 announce를 받은 피어 목록을 반환한다."""
        now = time.monotonic()
        result = []
        for info in self._discovered.values():
            if now - info["last_seen"] <= PEER_TTL_SEC:
                result.append(dict(info))
        return result

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------
    def _broadcast_announce(self) -> None:
        if not self._enabled:
            return
        try:
            nickname = self._get_nickname()
        except Exception:
            nickname = ""
        payload = {
            "type": ANNOUNCE_TYPE,
            "client_id": self._client_id,
            "nickname": nickname,
            "chat_port": self._chat_port,
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            self._socket.writeDatagram(data, QHostAddress.Broadcast, self._discovery_port)
        except Exception:
            pass

    def _on_ready_read(self) -> None:
        try:
            while self._socket.hasPendingDatagrams():
                datagram = self._socket.receiveDatagram()
                self._handle_datagram(datagram)
        except Exception:
            pass

    def _handle_datagram(self, datagram) -> None:
        try:
            data = bytes(datagram.data())
            sender = datagram.senderAddress()
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            return

        if not isinstance(payload, dict) or payload.get("type") != ANNOUNCE_TYPE:
            return

        client_id = payload.get("client_id")
        if not client_id or client_id == self._client_id:
            return

        nickname = payload.get("nickname") or client_id
        chat_port = payload.get("chat_port")
        if not isinstance(chat_port, int):
            return

        ip = sender.toString()
        # IPv4-mapped IPv6 표기(::ffff:x.x.x.x)를 순수 IPv4로 정리
        if ip.startswith("::ffff:"):
            ip = ip[len("::ffff:"):]

        self._discovered[client_id] = {
            "client_id": client_id,
            "nickname": nickname,
            "ip": ip,
            "chat_port": chat_port,
            "last_seen": time.monotonic(),
        }
        self.peer_discovered.emit(client_id, nickname, ip, chat_port)
