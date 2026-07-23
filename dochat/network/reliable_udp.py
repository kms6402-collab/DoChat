"""UDP 위에 ACK 기반 신뢰성(재전송)을 얹은 소켓 래퍼.

QUdpSocket을 직접 감싸며, ``needs_ack()``가 True인 패킷은 상대의 ACK를 받을
때까지 QTimer로 주기적으로 재전송한다. ACK가 필요 없는 패킷(PRESENCE 등)은
바로 보내고 잊는다(fire-and-forget).
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QHostAddress, QUdpSocket

from dochat.config import ACK_TIMEOUT_SEC, CLIENT_ID, MAX_RETRIES
from dochat.network.protocol import MsgType, Packet

# sender_id별로 최근에 본 seq를 이만큼 기억해 중복 수신을 걸러낸다.
_DEDUP_HISTORY = 256


def _normalize_ip(ip: str) -> str:
    """IPv4-매핑 IPv6 표기(예: ``::ffff:127.0.0.1``)를 순수 IPv4 문자열로 정규화한다.

    macOS 등 일부 플랫폼에서는 ``QHostAddress.Any``로 바인딩한 소켓이 수신 주소를
    이 형식으로 보고하는데, 그대로 두면 저장된 연락처의 순수 IPv4 문자열과
    비교했을 때 항상 불일치해 상대를 못 찾는다.
    """
    prefix = "::ffff:"
    if ip.lower().startswith(prefix):
        return ip[len(prefix):]
    return ip


class ReliableUDPSocket(QObject):
    """QUdpSocket을 감싸 ACK 기반 신뢰성을 제공하는 소켓.

    상위 레이어(ChatEngine 등)는 ``on_packet_received`` 콜백을 설정해
    ACK 이외의 모든 수신 패킷을 전달받는다. ACK 패킷 자체는 이 클래스
    내부에서 소비되어 상위 레이어로 올라가지 않는다.
    """

    def __init__(self, client_id: str = CLIENT_ID, parent: QObject | None = None):
        super().__init__(parent)
        self._client_id = client_id
        self.socket = QUdpSocket(self)

        # (packet, addr) -> callable(Packet, tuple[str,int]) 형태로 상위 레이어가 채워준다.
        self.on_packet_received: Optional[Callable[[Packet, tuple[str, int]], None]] = None

        self._seq_counter = 0
        # seq(int) -> {"packet", "addr", "on_ack", "on_fail", "retries", "timer"}
        self._pending: dict[int, dict] = {}
        # sender_id -> deque[seq] 최근 수신 이력 (중복 판정용)
        self._seen: dict[str, deque] = {}

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------
    def bind(self, port: int) -> bool:
        """지정 포트로 bind 하고 수신을 시작한다."""
        ok = self.socket.bind(QHostAddress.Any, port)
        if ok:
            self.socket.readyRead.connect(self._on_ready_read)
        return ok

    def send_reliable(
        self,
        packet: Packet,
        addr: tuple[str, int],
        on_ack: Optional[Callable[[], None]] = None,
        on_fail: Optional[Callable[[], None]] = None,
    ) -> int:
        """패킷을 보내고, ACK가 필요한 타입이면 재전송 타이머를 등록한다.

        Returns: 이 소켓이 발급한 seq 번호.
        """
        packet.seq = self._next_seq()
        self._write(packet, addr)

        if not packet.needs_ack():
            return packet.seq

        timer = QTimer(self)
        timer.setInterval(int(ACK_TIMEOUT_SEC * 1000))
        entry = {
            "packet": packet,
            "addr": addr,
            "on_ack": on_ack,
            "on_fail": on_fail,
            "retries": 0,
            "timer": timer,
        }
        self._pending[packet.seq] = entry
        timer.timeout.connect(lambda seq=packet.seq: self._on_timeout(seq))
        timer.start()
        return packet.seq

    def send_unreliable(self, packet: Packet, addr: tuple[str, int]) -> int:
        """ACK를 기다리지 않고 바로 전송한다 (PRESENCE 등)."""
        packet.seq = self._next_seq()
        self._write(packet, addr)
        return packet.seq

    def cancel(self, seq: int) -> None:
        """대기 중인 재전송을 취소한다 (필요 시 상위 레이어에서 사용)."""
        entry = self._pending.pop(seq, None)
        if entry is not None:
            entry["timer"].stop()
            entry["timer"].deleteLater()

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------
    def _next_seq(self) -> int:
        self._seq_counter += 1
        return self._seq_counter

    def _write(self, packet: Packet, addr: tuple[str, int]) -> None:
        self.socket.writeDatagram(packet.encode(), QHostAddress(addr[0]), addr[1])

    def _on_timeout(self, seq: int) -> None:
        entry = self._pending.get(seq)
        if entry is None:
            return  # 이미 ACK를 받아 정리됨

        entry["retries"] += 1
        if entry["retries"] > MAX_RETRIES:
            entry["timer"].stop()
            entry["timer"].deleteLater()
            del self._pending[seq]
            if entry["on_fail"]:
                entry["on_fail"]()
            return

        self._write(entry["packet"], entry["addr"])

    def _on_ready_read(self) -> None:
        while self.socket.hasPendingDatagrams():
            size = self.socket.pendingDatagramSize()
            data, host, port = self.socket.readDatagram(size)
            try:
                packet = Packet.decode(bytes(data))
            except Exception:
                # 손상되었거나 알 수 없는 형식의 데이터그램은 무시
                continue

            addr = (_normalize_ip(host.toString()), port)

            if packet.msg_type == MsgType.ACK:
                self._handle_ack(packet)
                continue

            is_dup = self._is_duplicate(packet)

            # 중복 여부와 무관하게 ACK는 항상 다시 보내준다 (내 ACK가 유실됐을 수 있으므로)
            if packet.needs_ack():
                self._send_ack(packet, addr)

            if not is_dup and self.on_packet_received:
                self.on_packet_received(packet, addr)

    def _handle_ack(self, ack_packet: Packet) -> None:
        orig_seq = ack_packet.payload.get("ack_seq")
        entry = self._pending.pop(orig_seq, None)
        if entry is None:
            return
        entry["timer"].stop()
        entry["timer"].deleteLater()
        if entry["on_ack"]:
            entry["on_ack"]()

    def _send_ack(self, orig_packet: Packet, addr: tuple[str, int]) -> None:
        ack = Packet(
            msg_type=MsgType.ACK,
            seq=0,
            sender_id=self._client_id,
            payload={"ack_seq": orig_packet.seq},
        )
        self.send_unreliable(ack, addr)

    def _is_duplicate(self, packet: Packet) -> bool:
        seen = self._seen.setdefault(packet.sender_id, deque(maxlen=_DEDUP_HISTORY))
        if packet.seq in seen:
            return True
        seen.append(packet.seq)
        return False
