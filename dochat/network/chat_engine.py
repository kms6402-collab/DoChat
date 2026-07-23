"""ChatEngine: DoChat 네트워크 레이어의 상위 API이자 UI의 유일한 진입점.

ReliableUDPSocket(전송) + PeerManager(연락처/프레즌스) + file_transfer(파일 송수신
상태)를 조합해, UI가 텍스트/파일/그룹 기능을 손쉽게 쓸 수 있는 시그널 기반
API를 제공한다.
"""
from __future__ import annotations

import os
import socket as _socket
import time
import uuid

from PySide6.QtCore import QObject, QTimer, Signal

from dochat.config import (
    CLIENT_ID,
    DEFAULT_LISTEN_PORT,
    DEFAULT_NETWORK_KEY,
    FILE_CHUNK_SIZE,
    FILE_WINDOW_SIZE,
    PRESENCE_INTERVAL_SEC,
)
from dochat.models.contact import Contact, Group
from dochat.models.message import (
    ConversationType,
    FileRecord,
    FileStatus,
    Message,
    MessageType,
)
from dochat.models.storage import Storage
from dochat.network.file_transfer import IncomingFileTransfer, OutgoingFileTransfer
from dochat.network.peer_manager import PeerManager
from dochat.network.protocol import MsgType, Packet, decode_file_chunk, encode_file_chunk
from dochat.network.reliable_udp import ReliableUDPSocket


class ChatEngine(QObject):
    """DoChat 네트워크 레이어의 최상위 API. UI는 이 클래스만 사용하면 된다."""

    message_received = Signal(object)          # Message 인스턴스 (storage 저장 완료 상태)
    file_progress = Signal(str, int, int, str)  # file_id, done_chunks, total_chunks, direction("in"|"out")
    file_completed = Signal(str, bool)          # file_id, success
    file_cancelled = Signal(str, str)           # file_id, direction("in"|"out")
    contact_status_changed = Signal(str, bool)  # contact_id, online
    group_updated = Signal(str)                 # group_id
    messages_read_up_to = Signal(str, float)    # conversation_id, up_to_ts (읽음 확인 도착)
    contact_added = Signal(str)                 # contact_id (상대가 나를 연락처로 추가했음을 HELLO로 알려옴)

    def __init__(self, storage: Storage, listen_port: int = DEFAULT_LISTEN_PORT, parent=None):
        super().__init__(parent)
        self.storage = storage
        self._client_id = CLIENT_ID
        self._listen_port = listen_port

        # 내 닉네임(설정 화면에서 변경 가능). 저장된 값이 없으면 OS 사용자명을 기본값으로 쓴다.
        self.my_nickname = storage.get_setting("my_nickname") or self._default_nickname()

        self.peer_manager = PeerManager(storage)
        self._groups: dict[str, Group] = {g.id: g for g in storage.get_groups()}

        # 오프라인 재전송 대기열: contact_id -> [{"message_id", "payload"}, ...]
        # 앱을 껐다 켜도 유지되도록, storage에 status='pending'으로 남아있는
        # (내가 보낸) TEXT 메시지를 읽어와 재구성한다.
        self._pending_retry: dict[str, list[dict]] = {}
        self._restore_pending_retry()

        # 원격 CLIENT_ID -> 로컬 Contact.id 매핑 (주소로 학습되거나 자동 생성됨)
        self._remote_to_local: dict[str, str] = {}
        # 마지막으로 UI에 알린 온라인 상태 (변화 감지용)
        self._online_state: dict[str, bool] = {}

        # 진행 중인 파일 전송 세션
        self._outgoing: dict[tuple[str, str], dict] = {}          # (file_id, contact_id) -> session
        self._incoming: dict[str, IncomingFileTransfer] = {}      # file_id -> transfer
        self._incoming_conv_type: dict[str, str] = {}             # file_id -> conversation_type
        self._incoming_sender_addr: dict[str, tuple[str, int]] = {}  # file_id -> 발신자 주소 (취소 통지용)

        self.socket = ReliableUDPSocket(
            client_id=self._client_id,
            parent=self,
            key=storage.get_setting("network_key") or DEFAULT_NETWORK_KEY,
        )
        self.socket.on_packet_received = self._on_packet_received
        if not self.socket.bind(listen_port):
            raise RuntimeError(f"UDP 포트 {listen_port} 바인딩에 실패했습니다.")

        # 그룹 초대 전파 시 "나 자신"을 상대측 연락처로 잘못 등록하지 않기
        # 위해, 이 노드가 스스로를 가리킬 수 있는 주소들을 미리 파악해둔다.
        # (실제 LAN IP뿐 아니라, 같은 머신에서 루프백 주소로 등록된 경우도
        # "나"로 인식해야 하므로 127.0.0.1/localhost도 함께 포함한다.)
        self._local_addrs = {
            (self._detect_local_ip(), listen_port),
            ("127.0.0.1", listen_port),
            ("localhost", listen_port),
        }

        # 하트비트 전송 타이머
        self._presence_send_timer = QTimer(self)
        self._presence_send_timer.setInterval(int(PRESENCE_INTERVAL_SEC * 1000))
        self._presence_send_timer.timeout.connect(self._send_presence_heartbeat)
        self._presence_send_timer.start()

        # 오프라인 전환 감지 타이머 (하트비트보다 촘촘하게 점검)
        self._presence_check_timer = QTimer(self)
        self._presence_check_timer.setInterval(max(int(PRESENCE_INTERVAL_SEC * 1000) // 2, 500))
        self._presence_check_timer.timeout.connect(self._check_presence_timeouts)
        self._presence_check_timer.start()

    # ------------------------------------------------------------------
    # 기본 프로퍼티 / 연락처 / 그룹 / 대화 조회
    # ------------------------------------------------------------------
    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def my_local_address(self) -> tuple[str, int]:
        """이 노드의 (IP, 포트). 다른 사람이 '새 대화 추가'에 입력할 값이다."""
        return (self._detect_local_ip(), self._listen_port)

    def set_my_nickname(self, nickname: str) -> None:
        """내 닉네임을 갱신하고 저장소에 영구 저장한다."""
        self.my_nickname = nickname
        self.storage.set_setting("my_nickname", nickname)

    @staticmethod
    def _default_nickname() -> str:
        try:
            return os.getlogin()
        except OSError:
            return "사용자"

    def add_contact(self, nickname: str, ip: str, port: int) -> Contact:
        contact = self.peer_manager.add_contact(nickname, ip, port)

        # 방금 추가한 상대에게 나를 알린다 (HELLO). 상대는 이를 받아 나를
        # 자신의 연락처로 자동 등록하고, 그 사실을 contact_added 시그널로
        # UI에 알려 대화가 자동으로 열리도록 한다 (main_window 참고).
        packet = Packet(
            msg_type=MsgType.HELLO,
            seq=0,
            sender_id=self.client_id,
            payload={"nickname": self.my_nickname},
        )
        self.socket.send_reliable(packet, contact.address)

        return contact

    def get_contacts(self) -> list[Contact]:
        return self.peer_manager.all_contacts()

    def get_contact(self, contact_id: str) -> Contact | None:
        return self.peer_manager.get_contact(contact_id)

    def update_contact(self, contact_id: str, nickname: str, ip: str, port: int) -> Contact | None:
        return self.peer_manager.update_contact(contact_id, nickname, ip, port)

    def remove_contact(self, contact_id: str) -> None:
        self.peer_manager.remove_contact(contact_id)

        # 해당 연락처가 속한 그룹들의 멤버 목록에서도 제거한다 (그룹 자체는 유지).
        for group in self._groups.values():
            if contact_id in group.member_ids:
                group.member_ids.remove(contact_id)
                self.storage.add_group(group)

    def leave_group(self, group_id: str) -> None:
        """로컬 그룹 목록/DB에서만 그룹을 제거한다 (다른 멤버에게는 알리지 않음)."""
        self._groups.pop(group_id, None)
        self.storage.remove_group(group_id)

    def create_group(self, name: str, member_ids: list[str]) -> Group:
        group = Group(id=str(uuid.uuid4()), name=name, member_ids=list(dict.fromkeys(member_ids)))
        self.storage.add_group(group)
        self._groups[group.id] = group

        members_payload = []
        for mid in group.member_ids:
            if mid == self.client_id:
                # 멤버 목록에 나 자신이 포함된 경우, 상대가 정확한 닉네임으로
                # 나를 표시할 수 있도록 내가 직접 설정한 닉네임을 실어 보낸다.
                my_ip, my_port = self.my_local_address
                members_payload.append(
                    {"id": self.client_id, "nickname": self.my_nickname, "ip": my_ip, "port": my_port}
                )
                continue
            contact = self.peer_manager.get_contact(mid)
            if contact:
                members_payload.append(
                    {"id": contact.id, "nickname": contact.nickname, "ip": contact.ip, "port": contact.port}
                )

        for contact in self._resolve_targets(group.id, ConversationType.GROUP):
            packet = Packet(
                msg_type=MsgType.GROUP_INVITE,
                seq=0,
                sender_id=self.client_id,
                payload={"group_id": group.id, "name": group.name, "members": members_payload},
            )
            self.socket.send_reliable(packet, contact.address)

        return group

    def _build_members_payload(self, member_ids: list[str]) -> list[dict]:
        """member_ids에 대응하는 {"id","nickname","ip","port"} 목록을 만든다.

        create_group()의 members_payload 구성 방식과 동일하게, 목록에 나 자신이
        포함된 경우 내가 직접 설정한 닉네임/주소를 실어 보낸다.
        """
        members_payload = []
        for mid in member_ids:
            if mid == self.client_id:
                my_ip, my_port = self.my_local_address
                members_payload.append(
                    {"id": self.client_id, "nickname": self.my_nickname, "ip": my_ip, "port": my_port}
                )
                continue
            contact = self.peer_manager.get_contact(mid)
            if contact:
                members_payload.append(
                    {"id": contact.id, "nickname": contact.nickname, "ip": contact.ip, "port": contact.port}
                )
        return members_payload

    def add_group_members(self, group_id: str, contact_ids: list[str]) -> None:
        """그룹에 새 멤버들을 추가하고, 갱신된 전체 멤버 목록을 모든 멤버에게 전파한다."""
        group = self._groups.get(group_id)
        if group is None:
            return

        group.member_ids = list(dict.fromkeys(group.member_ids + contact_ids))
        self.storage.add_group(group)

        members_payload = self._build_members_payload(group.member_ids)

        # 갱신 후 멤버 전원(나 자신 제외)에게 알린다. (새로 추가된 멤버 포함)
        targets_ids = [mid for mid in group.member_ids if mid != self.client_id]
        for mid in targets_ids:
            contact = self.peer_manager.get_contact(mid)
            if not contact:
                continue
            packet = Packet(
                msg_type=MsgType.GROUP_MEMBER_UPDATE,
                seq=0,
                sender_id=self.client_id,
                payload={
                    "group_id": group.id,
                    "name": group.name,
                    "action": "add",
                    "members": members_payload,
                },
            )
            self.socket.send_reliable(packet, contact.address)

    def remove_group_member(self, group_id: str, contact_id: str) -> None:
        """그룹에서 멤버 한 명을 제거하고, 갱신된 전체 멤버 목록을 이전 멤버 전원에게 전파한다."""
        group = self._groups.get(group_id)
        if group is None:
            return

        previous_members = list(group.member_ids)
        if contact_id in group.member_ids:
            group.member_ids.remove(contact_id)
        self.storage.add_group(group)

        members_payload = self._build_members_payload(group.member_ids)

        # 제거된 사람도 "빠졌다"는 사실을 알아야 하므로, 이전 멤버 전원(나 자신 제외)에게 알린다.
        for mid in previous_members:
            if mid == self.client_id:
                continue
            contact = self.peer_manager.get_contact(mid)
            if not contact:
                continue
            packet = Packet(
                msg_type=MsgType.GROUP_MEMBER_UPDATE,
                seq=0,
                sender_id=self.client_id,
                payload={
                    "group_id": group.id,
                    "name": group.name,
                    "action": "remove",
                    "members": members_payload,
                },
            )
            self.socket.send_reliable(packet, contact.address)

    def get_groups(self) -> list[Group]:
        return list(self._groups.values())

    def get_conversation_messages(self, conversation_id: str) -> list[Message]:
        return self.storage.get_messages(conversation_id)

    def get_all_files(self) -> list[FileRecord]:
        return self.storage.get_all_files()

    # ------------------------------------------------------------------
    # 읽음 확인
    # ------------------------------------------------------------------
    def mark_conversation_read(self, conversation_id: str, conversation_type: str) -> None:
        """상대(들)가 보낸 메시지 중 가장 최근 타임스탬프까지 읽었다고 알린다."""
        messages = self.storage.get_messages(conversation_id)
        latest_ts: float | None = None
        for message in messages:
            if message.sender_id == self.client_id:
                continue
            if latest_ts is None or message.timestamp > latest_ts:
                latest_ts = message.timestamp

        if latest_ts is None:
            return  # 상대가 보낸 메시지가 없으면 알릴 것도 없다.

        payload = {
            "conversation_id": conversation_id,
            "conversation_type": conversation_type,
            "up_to_ts": latest_ts,
        }
        for contact in self._resolve_targets(conversation_id, conversation_type):
            packet = Packet(msg_type=MsgType.READ_RECEIPT, seq=0, sender_id=self.client_id, payload=payload)
            self.socket.send_reliable(packet, contact.address)

    # ------------------------------------------------------------------
    # 텍스트 전송
    # ------------------------------------------------------------------
    def send_text(self, conversation_id: str, conversation_type: str, text: str) -> Message:
        message = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            sender_id=self.client_id,
            type=MessageType.TEXT,
            timestamp=time.time(),
            text=text,
        )
        self.storage.add_message(message)

        group_id = conversation_id if conversation_type == ConversationType.GROUP else None
        for contact in self._resolve_targets(conversation_id, conversation_type):
            payload = {
                "message_id": message.id,
                "conversation_type": conversation_type,
                "group_id": group_id,
                "text": text,
                "timestamp": message.timestamp,
            }
            packet = Packet(msg_type=MsgType.TEXT, seq=0, sender_id=self.client_id, payload=payload)

            def _on_fail(contact_id=contact.id, message_id=message.id, payload=payload) -> None:
                # 상대가 오프라인이라 MAX_RETRIES 소진 -> 재전송 대기열에 넣는다.
                self.storage.mark_message_status(message_id, "pending")
                self._queue_pending_retry(contact_id, message_id, payload)

            self.socket.send_reliable(packet, contact.address, on_fail=_on_fail)

        return message

    # ------------------------------------------------------------------
    # 오프라인 재전송 큐 (TEXT 메시지 전용)
    # ------------------------------------------------------------------
    def _queue_pending_retry(self, contact_id: str, message_id: str, payload: dict) -> None:
        """재전송이 필요한 (contact, message) 쌍을 대기열에 기록한다 (중복 방지)."""
        entries = self._pending_retry.setdefault(contact_id, [])
        if any(e["message_id"] == message_id for e in entries):
            return
        entries.append({"message_id": message_id, "payload": payload})

    def _remove_pending_retry(self, contact_id: str, message_id: str) -> None:
        entries = self._pending_retry.get(contact_id)
        if not entries:
            return
        remaining = [e for e in entries if e["message_id"] != message_id]
        if remaining:
            self._pending_retry[contact_id] = remaining
        else:
            self._pending_retry.pop(contact_id, None)

    def _restore_pending_retry(self) -> None:
        """재시작 후에도 대기열이 유지되도록, storage에서 pending 상태의
        (내가 보낸) TEXT 메시지를 읽어와 ``_pending_retry``를 재구성한다."""
        for message in self.storage.get_all_pending_messages():
            if message.sender_id != self._client_id or message.type != MessageType.TEXT:
                continue

            if message.conversation_type == ConversationType.GROUP:
                group = self._groups.get(message.conversation_id)
                if not group:
                    continue
                contact_ids = [mid for mid in group.member_ids if mid != self._client_id]
                group_id = message.conversation_id
            else:
                contact_ids = [message.conversation_id]
                group_id = None

            payload = {
                "message_id": message.id,
                "conversation_type": message.conversation_type,
                "group_id": group_id,
                "text": message.text,
                "timestamp": message.timestamp,
            }
            for contact_id in contact_ids:
                self._queue_pending_retry(contact_id, message.id, payload)

    def _retry_pending_for_contact(self, contact_id: str) -> None:
        """해당 연락처가 온라인으로 전환됐을 때 대기 중인 메시지를 재전송한다."""
        entries = self._pending_retry.get(contact_id)
        if not entries:
            return
        contact = self.peer_manager.get_contact(contact_id)
        if contact is None:
            return

        for entry in list(entries):
            message_id = entry["message_id"]
            payload = entry["payload"]
            packet = Packet(msg_type=MsgType.TEXT, seq=0, sender_id=self.client_id, payload=payload)

            def _on_ack(contact_id=contact_id, message_id=message_id) -> None:
                self.storage.mark_message_status(message_id, "sent")
                self._remove_pending_retry(contact_id, message_id)

            def _on_fail(contact_id=contact_id, message_id=message_id, payload=payload) -> None:
                # 다시 실패하면 큐에 그대로 남겨두고 다음 온라인 전환을 기다린다.
                self.storage.mark_message_status(message_id, "pending")
                self._queue_pending_retry(contact_id, message_id, payload)

            self.socket.send_reliable(packet, contact.address, on_ack=_on_ack, on_fail=_on_fail)

    # ------------------------------------------------------------------
    # 파일 전송
    # ------------------------------------------------------------------
    def send_file(self, conversation_id: str, conversation_type: str, file_path: str) -> str:
        file_id = str(uuid.uuid4())

        try:
            probe = OutgoingFileTransfer(file_path, file_id=file_id)
        except OSError:
            # 파일을 열 수 없음 -> 즉시 실패로 기록
            record = FileRecord(
                file_id=file_id,
                filename=file_path,
                size=0,
                mime_type="application/octet-stream",
                local_path=file_path,
                status=FileStatus.FAILED,
                timestamp=time.time(),
                conversation_id=conversation_id,
                direction="out",
            )
            self.storage.add_file_record(record)
            QTimer.singleShot(0, lambda: self.file_completed.emit(file_id, False))
            return file_id

        record = FileRecord(
            file_id=file_id,
            filename=probe.filename,
            size=probe.size,
            mime_type=probe.mime_type,
            local_path=str(probe.file_path),
            status=FileStatus.SENDING,
            timestamp=time.time(),
            conversation_id=conversation_id,
            direction="out",
        )
        self.storage.add_file_record(record)

        targets = self._resolve_targets(conversation_id, conversation_type)
        if not targets:
            self.storage.update_file_status(file_id, FileStatus.FAILED)
            QTimer.singleShot(0, lambda: self.file_completed.emit(file_id, False))
            return file_id

        for i, contact in enumerate(targets):
            transfer = probe if i == 0 else OutgoingFileTransfer(file_path, file_id=file_id)
            session = {
                "transfer": transfer,
                "contact": contact,
                "conversation_id": conversation_id,
                "conversation_type": conversation_type,
                "pending_seqs": set(),  # 아직 ACK를 못 받은 send_reliable() 발급 seq들 (취소 시 정리용)
            }
            self._outgoing[(file_id, contact.id)] = session
            self._send_file_meta(session)

        return file_id

    def _send_file_meta(self, session: dict) -> None:
        transfer: OutgoingFileTransfer = session["transfer"]
        conversation_type = session["conversation_type"]
        payload = {
            "file_id": transfer.file_id,
            "filename": transfer.filename,
            "size": transfer.size,
            "mime_type": transfer.mime_type,
            "total_chunks": transfer.total_chunks,
            "conversation_type": conversation_type,
            "group_id": session["conversation_id"] if conversation_type == ConversationType.GROUP else None,
        }
        packet = Packet(msg_type=MsgType.FILE_META, seq=0, sender_id=self.client_id, payload=payload)
        self.socket.send_reliable(
            packet,
            session["contact"].address,
            on_ack=lambda: self._pump_send_window(session),
            on_fail=lambda: self._finish_outgoing(session, False),
        )

    def _pump_send_window(self, session: dict) -> None:
        """윈도우(파이프라인)에 빈 자리가 있는 만큼 새 청크를 발송한다."""
        transfer: OutgoingFileTransfer = session["transfer"]
        while len(transfer.in_flight) < FILE_WINDOW_SIZE:
            nxt = transfer.dispatch_next()
            if nxt is None:
                break
            index, data = nxt
            self._send_one_chunk(session, index, data)

    def _send_one_chunk(self, session: dict, index: int, data: bytes) -> None:
        transfer: OutgoingFileTransfer = session["transfer"]
        offset = index * FILE_CHUNK_SIZE
        payload = {
            "file_id": transfer.file_id,
            "index": index,
            "offset": offset,
            "total_chunks": transfer.total_chunks,
            "data": encode_file_chunk(data),
            "is_last": index == transfer.total_chunks - 1,
        }
        packet = Packet(msg_type=MsgType.FILE_CHUNK, seq=0, sender_id=self.client_id, payload=payload)

        def _on_ack() -> None:
            transfer.mark_acked(index)
            session["pending_seqs"].discard(seq)
            self.file_progress.emit(transfer.file_id, transfer.acked_count, transfer.total_chunks, "out")
            if transfer.is_fully_acked:
                self._finish_outgoing(session, True)
            else:
                self._pump_send_window(session)  # 창에 빈 자리가 생겼으니 다음 청크를 채운다

        def _on_fail() -> None:
            self._finish_outgoing(session, False)

        seq = self.socket.send_reliable(packet, session["contact"].address, on_ack=_on_ack, on_fail=_on_fail)
        session["pending_seqs"].add(seq)

    def _finish_outgoing(self, session: dict, success: bool) -> None:
        transfer: OutgoingFileTransfer = session["transfer"]
        contact: Contact = session["contact"]
        file_id = transfer.file_id
        key = (file_id, contact.id)

        if key not in self._outgoing:
            # 파이프라이닝 중 동시에 여러 in-flight 청크가 실패하거나, 이미
            # 취소/완료 처리된 세션에 대해 뒤늦게 콜백이 들어온 경우 -> 중복 처리 방지.
            return

        self._outgoing.pop(key, None)
        self.storage.update_file_status(file_id, FileStatus.COMPLETED if success else FileStatus.FAILED)

        if success:
            message = Message(
                id=str(uuid.uuid4()),
                conversation_id=session["conversation_id"],
                conversation_type=session["conversation_type"],
                sender_id=self.client_id,
                type=MessageType.FILE,
                timestamp=time.time(),
                file_id=file_id,
            )
            self.storage.add_message(message)

        self.file_completed.emit(file_id, success)

    # ------------------------------------------------------------------
    # 프레즌스 (하트비트)
    # ------------------------------------------------------------------
    def _send_presence_heartbeat(self) -> None:
        for contact in self.peer_manager.all_contacts():
            packet = Packet(
                msg_type=MsgType.PRESENCE,
                seq=0,
                sender_id=self.client_id,
                payload={"nickname": self.my_nickname},
            )
            self.socket.send_unreliable(packet, contact.address)

    def _check_presence_timeouts(self) -> None:
        for contact in self.peer_manager.all_contacts():
            self._update_online_state(contact.id)

    def _update_online_state(self, contact_id: str) -> None:
        contact = self.peer_manager.get_contact(contact_id)
        if contact is None:
            return
        now_online = contact.online
        was_online = self._online_state.get(contact_id, False)
        if now_online != was_online:
            self._online_state[contact_id] = now_online
            self.contact_status_changed.emit(contact_id, now_online)
            if now_online:
                # 오프라인 -> 온라인 전환: 대기 중인 재전송 메시지가 있으면 다시 시도한다.
                self._retry_pending_for_contact(contact_id)

    # ------------------------------------------------------------------
    # 수신 패킷 처리
    # ------------------------------------------------------------------
    def _on_packet_received(self, packet: Packet, addr: tuple[str, int]) -> None:
        handler = {
            MsgType.TEXT: self._handle_text,
            MsgType.PRESENCE: self._handle_presence,
            MsgType.HELLO: self._handle_hello,
            MsgType.GROUP_INVITE: self._handle_group_invite,
            MsgType.GROUP_MEMBER_UPDATE: self._handle_group_member_update,
            MsgType.FILE_META: self._handle_file_meta,
            MsgType.FILE_CHUNK: self._handle_file_chunk,
            MsgType.FILE_CANCEL: self._handle_file_cancel,
            MsgType.READ_RECEIPT: self._handle_read_receipt,
        }.get(packet.msg_type)
        if handler:
            handler(packet, addr)

    def _handle_presence(self, packet: Packet, addr: tuple[str, int]) -> None:
        nickname = (packet.payload or {}).get("nickname")
        contact_id = self._resolve_contact(packet.sender_id, addr[0], addr[1], nickname=nickname)
        self.peer_manager.mark_online(contact_id)
        self._update_online_state(contact_id)

    def _handle_hello(self, packet: Packet, addr: tuple[str, int]) -> None:
        """상대가 나를 연락처로 추가하며 보낸 HELLO. 나도 상대를 로컬 연락처로
        자동 등록하고, UI가 해당 대화를 자동으로 열 수 있도록 알린다."""
        nickname = (packet.payload or {}).get("nickname")
        contact_id = self._resolve_contact(packet.sender_id, addr[0], addr[1], nickname=nickname)
        self.peer_manager.mark_online(contact_id)
        self._update_online_state(contact_id)
        self.contact_added.emit(contact_id)

    def _handle_text(self, packet: Packet, addr: tuple[str, int]) -> None:
        payload = packet.payload
        conversation_type = payload.get("conversation_type", ConversationType.DIRECT)

        if conversation_type == ConversationType.GROUP:
            conversation_id = payload.get("group_id")
        else:
            conversation_id = self._resolve_contact(packet.sender_id, addr[0], addr[1])

        # 상대가 살아있다는 신호이기도 하므로 온라인 상태도 갱신
        sender_contact_id = self._resolve_contact(packet.sender_id, addr[0], addr[1])
        self.peer_manager.mark_online(sender_contact_id)
        self._update_online_state(sender_contact_id)

        message = Message(
            id=payload.get("message_id") or str(uuid.uuid4()),
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            sender_id=packet.sender_id,
            type=MessageType.TEXT,
            timestamp=payload.get("timestamp", time.time()),
            text=payload.get("text"),
        )
        self.storage.add_message(message)
        self.message_received.emit(message)

    def _handle_read_receipt(self, packet: Packet, addr: tuple[str, int]) -> None:
        payload = packet.payload or {}
        up_to_ts = payload.get("up_to_ts")
        if up_to_ts is None:
            return

        conversation_type = payload.get("conversation_type", ConversationType.DIRECT)
        if conversation_type == ConversationType.GROUP:
            # 그룹은 group_id가 양쪽 모두 동일한 전역 식별자이므로 그대로 사용한다.
            conversation_id = payload.get("conversation_id")
        else:
            # 1:1 대화의 conversation_id는 상대측 로컬 contact.id라 내 쪽과
            # 값이 다를 수 있다 (_handle_text와 동일하게 발신자 기준으로
            # 내 로컬 contact.id를 다시 계산해야 한다).
            conversation_id = self._resolve_contact(packet.sender_id, addr[0], addr[1])
        if conversation_id is None:
            return

        now = time.time()
        updated = False
        for message in self.storage.get_messages(conversation_id):
            if (
                message.sender_id == self.client_id
                and message.read_at is None
                and message.timestamp <= up_to_ts
            ):
                self.storage.mark_message_read(message.id, now)
                updated = True

        if updated:
            self.messages_read_up_to.emit(conversation_id, up_to_ts)

    def _handle_group_invite(self, packet: Packet, addr: tuple[str, int]) -> None:
        payload = packet.payload
        group_id = payload.get("group_id")
        name = payload.get("name", "")
        members_info = payload.get("members", [])
        if not group_id:
            return

        member_ids: list[str] = []

        # 초대를 보낸 사람을 연락처로 확보
        inviter_id = self._resolve_contact(packet.sender_id, addr[0], addr[1])
        member_ids.append(inviter_id)

        for info in members_info:
            remote_id = info.get("id")
            ip, port = info.get("ip"), info.get("port")
            nickname = info.get("nickname")
            if remote_id is None or ip is None or port is None:
                continue
            if (ip, port) in self._local_addrs:
                # 초대장 발신자 기준 멤버 목록에 포함된 "나 자신" 항목이므로
                # 스스로를 연락처/그룹 멤버로 등록하지 않는다.
                continue
            local_id = self._resolve_contact(remote_id, ip, port, nickname=nickname)
            if local_id not in member_ids:
                member_ids.append(local_id)

        group = Group(id=group_id, name=name, member_ids=member_ids)
        self.storage.add_group(group)
        self._groups[group.id] = group
        self.group_updated.emit(group.id)

    def _handle_group_member_update(self, packet: Packet, addr: tuple[str, int]) -> None:
        """다른 멤버가 전파한 멤버 추가/삭제(GROUP_MEMBER_UPDATE)를 반영한다.

        _handle_group_invite()와 거의 동일한 방식으로 payload의 members를 로컬
        연락처로 변환한다. 다만 이번 members는 "갱신 후 전체 멤버 목록"이므로,
        그 안에 내 자신의 항목이 존재하는지 여부로 "내가 여전히 멤버인지"를
        판단한다 (없으면 그룹에서 제거된 것).
        """
        payload = packet.payload
        group_id = payload.get("group_id")
        name = payload.get("name", "")
        members_info = payload.get("members", [])
        if not group_id:
            return

        i_am_member = any(
            info.get("ip") is not None
            and info.get("port") is not None
            and (info.get("ip"), info.get("port")) in self._local_addrs
            for info in members_info
        )

        if not i_am_member:
            # 갱신된 멤버 목록에 내가 없다 = 내가 그룹에서 제거됨.
            self._groups.pop(group_id, None)
            self.storage.remove_group(group_id)
            self.group_updated.emit(group_id)
            return

        member_ids: list[str] = []

        # 이 갱신을 보낸 사람(그룹 내 누구든 가능)을 연락처로 확보
        sender_id = self._resolve_contact(packet.sender_id, addr[0], addr[1])
        member_ids.append(sender_id)

        for info in members_info:
            remote_id = info.get("id")
            ip, port = info.get("ip"), info.get("port")
            nickname = info.get("nickname")
            if remote_id is None or ip is None or port is None:
                continue
            if (ip, port) in self._local_addrs:
                # 나 자신을 가리키는 항목이므로 연락처/멤버로 등록하지 않는다.
                continue
            local_id = self._resolve_contact(remote_id, ip, port, nickname=nickname)
            if local_id not in member_ids:
                member_ids.append(local_id)

        group = Group(id=group_id, name=name, member_ids=member_ids)
        self.storage.add_group(group)
        self._groups[group.id] = group
        self.group_updated.emit(group.id)

    def _handle_file_meta(self, packet: Packet, addr: tuple[str, int]) -> None:
        payload = packet.payload
        file_id = payload.get("file_id")
        if not file_id:
            return

        conversation_type = payload.get("conversation_type", ConversationType.DIRECT)
        if conversation_type == ConversationType.GROUP:
            conversation_id = payload.get("group_id")
        else:
            conversation_id = self._resolve_contact(packet.sender_id, addr[0], addr[1])

        transfer = IncomingFileTransfer(
            file_id=file_id,
            filename=payload.get("filename") or file_id,
            size=payload.get("size", 0),
            mime_type=payload.get("mime_type", "application/octet-stream"),
            total_chunks=payload.get("total_chunks", 1),
            conversation_id=conversation_id,
        )
        self._incoming[file_id] = transfer
        self._incoming_conv_type[file_id] = conversation_type
        self._incoming_sender_addr[file_id] = addr  # 취소 통지를 보낼 때 필요

        record = FileRecord(
            file_id=file_id,
            filename=transfer.filename,
            size=transfer.size,
            mime_type=transfer.mime_type,
            local_path=str(transfer.tmp_path),
            status=FileStatus.RECEIVING,
            timestamp=time.time(),
            conversation_id=conversation_id,
            direction="in",
        )
        self.storage.add_file_record(record)
        self.file_progress.emit(file_id, 0, transfer.total_chunks, "in")

    def _handle_file_chunk(self, packet: Packet, addr: tuple[str, int]) -> None:
        payload = packet.payload
        file_id = payload.get("file_id")
        transfer = self._incoming.get(file_id) if file_id else None
        if transfer is None:
            # FILE_META를 받지 못했거나 이미 완료된 뒤 도착한 지연/중복 청크
            return

        index = payload.get("index", 0)
        offset = payload.get("offset", index * FILE_CHUNK_SIZE)
        data = decode_file_chunk(payload.get("data", ""))
        transfer.write_chunk(index, offset, data)

        done, total = transfer.progress()
        self.file_progress.emit(file_id, done, total, "in")

        if transfer.is_complete:
            final_path = transfer.finalize()
            conversation_type = self._incoming_conv_type.pop(file_id, ConversationType.DIRECT)
            self._incoming.pop(file_id, None)
            self._incoming_sender_addr.pop(file_id, None)

            record = self.storage.get_file_record(file_id)
            if record is not None:
                record.local_path = final_path
                record.status = FileStatus.COMPLETED
                self.storage.add_file_record(record)

            message = Message(
                id=str(uuid.uuid4()),
                conversation_id=transfer.conversation_id,
                conversation_type=conversation_type,
                sender_id=packet.sender_id,
                type=MessageType.FILE,
                timestamp=time.time(),
                file_id=file_id,
            )
            self.storage.add_message(message)
            self.file_completed.emit(file_id, True)

    def _handle_file_cancel(self, packet: Packet, addr: tuple[str, int]) -> None:
        """상대가 FILE_CANCEL을 보내온 경우(자기 쪽 취소)를 로컬에 반영한다.

        상대가 이미 취소를 결정했으므로, 무한루프 방지를 위해 여기서는
        다시 FILE_CANCEL을 돌려보내지 않고 로컬 정리만 수행한다.
        """
        file_id = (packet.payload or {}).get("file_id")
        if not file_id:
            return

        # 내가 보내는 중이던 파일 -> 상대가 수신을 취소한 경우
        for key in [k for k in self._outgoing if k[0] == file_id]:
            session = self._outgoing.pop(key, None)
            if session is None:
                continue
            for seq in session.get("pending_seqs", set()):
                self.socket.cancel(seq)
            self.storage.update_file_status(file_id, FileStatus.CANCELLED)
            self.file_cancelled.emit(file_id, "out")

        # 내가 받는 중이던 파일 -> 상대가 발신을 취소한 경우
        transfer = self._incoming.pop(file_id, None)
        if transfer is not None:
            transfer.abort()
            self._incoming_conv_type.pop(file_id, None)
            self._incoming_sender_addr.pop(file_id, None)
            self.storage.update_file_status(file_id, FileStatus.CANCELLED)
            self.file_cancelled.emit(file_id, "in")

    def cancel_outgoing_file(self, file_id: str) -> None:
        """내가 보내는 중인 파일 전송을 취소한다 (그룹이면 대상 전원에 대해)."""
        keys = [k for k in self._outgoing if k[0] == file_id]
        if not keys:
            return

        for key in keys:
            session = self._outgoing.pop(key, None)
            if session is None:
                continue
            contact: Contact = session["contact"]
            for seq in session.get("pending_seqs", set()):
                self.socket.cancel(seq)
            packet = Packet(
                msg_type=MsgType.FILE_CANCEL,
                seq=0,
                sender_id=self.client_id,
                payload={"file_id": file_id},
            )
            self.socket.send_reliable(packet, contact.address)

        self.storage.update_file_status(file_id, FileStatus.CANCELLED)
        self.file_cancelled.emit(file_id, "out")

    def cancel_incoming_file(self, file_id: str) -> None:
        """내가 받는 중인 파일 전송을 취소한다 (임시 파일 정리 + 상대에게 통지)."""
        transfer = self._incoming.pop(file_id, None)
        if transfer is None:
            return

        transfer.abort()
        self._incoming_conv_type.pop(file_id, None)
        sender_addr = self._incoming_sender_addr.pop(file_id, None)

        if sender_addr is not None:
            packet = Packet(
                msg_type=MsgType.FILE_CANCEL,
                seq=0,
                sender_id=self.client_id,
                payload={"file_id": file_id},
            )
            self.socket.send_reliable(packet, sender_addr)

        self.storage.update_file_status(file_id, FileStatus.CANCELLED)
        self.file_cancelled.emit(file_id, "in")

    # ------------------------------------------------------------------
    # 연락처 식별 (원격 CLIENT_ID/주소 <-> 로컬 Contact.id)
    # ------------------------------------------------------------------
    def _resolve_contact(self, remote_id: str, ip: str, port: int, nickname: str | None = None) -> str:
        """원격 CLIENT_ID를 로컬 Contact.id로 변환한다.

        이미 알고 있는 매핑이면 그대로 쓰고, 아니면 (ip, port)가 일치하는 기존
        연락처를 찾는다. 그마저도 없으면(사전에 등록되지 않은 상대) remote_id를
        그대로 로컬 id로 사용해 새 연락처를 자동 생성한다.
        """
        if remote_id in self._remote_to_local:
            return self._remote_to_local[remote_id]

        for contact in self.peer_manager.all_contacts():
            if contact.ip == ip and contact.port == port:
                self._remote_to_local[remote_id] = contact.id
                return contact.id

        contact = Contact(id=remote_id, nickname=nickname or remote_id[:8], ip=ip, port=port)
        self.storage.add_contact(contact)
        self.peer_manager.contacts[contact.id] = contact
        self._remote_to_local[remote_id] = contact.id
        return contact.id

    @staticmethod
    def _detect_local_ip() -> str:
        """이 노드가 LAN에서 실제로 사용하는(외부에서 보이는) IP를 추정한다.

        실제로 패킷을 보내지는 않고 OS 라우팅 테이블을 통해 소켓의 로컬
        주소만 조회하는 방식이라 네트워크 연결이 없어도 안전하다.
        """
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            s.close()

    def _resolve_targets(self, conversation_id: str, conversation_type: str) -> list[Contact]:
        if conversation_type == ConversationType.GROUP:
            group = self._groups.get(conversation_id)
            if not group:
                return []
            targets = []
            for member_id in group.member_ids:
                if member_id == self.client_id:
                    continue
                contact = self.peer_manager.get_contact(member_id)
                if contact:
                    targets.append(contact)
            return targets

        contact = self.peer_manager.get_contact(conversation_id)
        return [contact] if contact else []
