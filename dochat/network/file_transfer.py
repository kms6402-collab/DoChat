"""파일 송수신 진행 상태를 관리하는 헬퍼 클래스들.

``OutgoingFileTransfer``는 파이프라이닝(윈도우) 방식을 지원한다: 여러 청크를
동시에 "발송했지만 아직 ACK 안 받음(in-flight)" 상태로 둘 수 있다. 실제
네트워크 송수신 트리거는 ``ChatEngine``이 담당하고, 여기서는 파일 I/O와
진행 상태만 다룬다.
"""
from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path

import dochat.config as config
from dochat.config import FILE_CHUNK_SIZE


class OutgoingFileTransfer:
    """보낼 파일을 청크로 미리 분할해 들고 있으면서 파이프라인 진행 상태를 추적한다.

    ``next_to_send``까지는 아직 "새로 발송"하지 않은 인덱스이고, 그 이전 인덱스들은
    이미 발송을 시작했다는 뜻이다. 발송했지만 아직 ACK를 못 받은 인덱스는
    ``in_flight``에 남아있고, ACK를 받으면 거기서 빠지며 ``acked_count``가 늘어난다.
    """

    def __init__(self, file_path: str, file_id: str | None = None):
        self.file_path = Path(file_path)
        self.file_id = file_id or str(uuid.uuid4())
        self.filename = self.file_path.name
        self.size = self.file_path.stat().st_size
        self.mime_type = mimetypes.guess_type(str(self.file_path))[0] or "application/octet-stream"

        with open(self.file_path, "rb") as f:
            data = f.read()

        if data:
            self.chunks: list[bytes] = [
                data[i : i + FILE_CHUNK_SIZE] for i in range(0, len(data), FILE_CHUNK_SIZE)
            ]
        else:
            # 빈 파일도 최소 한 번은 전송/완료 처리가 되도록 빈 청크 1개를 둔다.
            self.chunks = [b""]

        self.total_chunks = len(self.chunks)
        self.next_to_send = 0  # 다음에 "새로" 발송할 청크 인덱스
        self.in_flight: set[int] = set()  # 발송했지만 아직 ACK 못 받은 인덱스들
        self.acked_count = 0  # ACK 받은 청크 수 (진행률 표시용)

    def dispatch_next(self) -> tuple[int, bytes] | None:
        """다음 청크를 in-flight로 표시하고 (index, data)를 돌려준다. 더 없으면 None."""
        if self.next_to_send >= self.total_chunks:
            return None
        index = self.next_to_send
        self.next_to_send += 1
        self.in_flight.add(index)
        return index, self.chunks[index]

    def mark_acked(self, index: int) -> None:
        """해당 인덱스의 ACK를 받았음을 기록한다."""
        self.in_flight.discard(index)
        self.acked_count += 1

    @property
    def has_pending_dispatch(self) -> bool:
        return self.next_to_send < self.total_chunks

    @property
    def is_fully_acked(self) -> bool:
        return self.acked_count >= self.total_chunks

    @property
    def done_chunks(self) -> int:
        return self.acked_count


class IncomingFileTransfer:
    """FILE_META 수신 시 생성되어 청크들을 받아 임시 파일에 기록한다."""

    def __init__(
        self,
        file_id: str,
        filename: str,
        size: int,
        mime_type: str,
        total_chunks: int,
        conversation_id: str,
    ):
        self.file_id = file_id
        self.filename = filename
        self.size = size
        self.mime_type = mime_type
        self.total_chunks = max(total_chunks, 1)
        self.conversation_id = conversation_id
        self.received_chunks = 0
        self._received_indices: set[int] = set()

        config.RECEIVED_FILES_DIR.mkdir(parents=True, exist_ok=True)
        self.tmp_path = config.RECEIVED_FILES_DIR / f"{file_id}.part"
        with open(self.tmp_path, "wb") as f:
            if size > 0:
                f.truncate(size)

    def write_chunk(self, index: int, offset: int, data: bytes) -> bool:
        """오프셋에 맞춰 청크를 기록한다. 새로 받은 청크면 True, 중복이면 False."""
        if index in self._received_indices:
            return False
        with open(self.tmp_path, "r+b") as f:
            f.seek(offset)
            f.write(data)
        self._received_indices.add(index)
        self.received_chunks += 1
        return True

    @property
    def is_complete(self) -> bool:
        return self.received_chunks >= self.total_chunks

    def progress(self) -> tuple[int, int]:
        return self.received_chunks, self.total_chunks

    def finalize(self) -> str:
        """완료된 임시 파일을 RECEIVED_FILES_DIR의 최종 파일명으로 옮기고 경로를 반환한다."""
        final_path = _unique_path(config.RECEIVED_FILES_DIR / self.filename)
        shutil.move(str(self.tmp_path), str(final_path))
        return str(final_path)

    def abort(self) -> None:
        """실패 시 임시 파일을 정리한다."""
        try:
            self.tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _unique_path(path: Path) -> Path:
    """같은 이름의 파일이 이미 있으면 (1), (2) ... 를 붙여 충돌을 피한다."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem}({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1
