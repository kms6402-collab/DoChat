"""파일 송수신 진행 상태를 관리하는 헬퍼 클래스들.

stop-and-wait 방식(청크 하나 보내고 ACK 받은 뒤 다음 청크)만 지원하므로
윈도우/파이프라이닝 로직은 없다. 실제 네트워크 송수신 트리거는
``ChatEngine``이 담당하고, 여기서는 파일 I/O와 진행 상태만 다룬다.
"""
from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path

from dochat.config import FILE_CHUNK_SIZE, RECEIVED_FILES_DIR


class OutgoingFileTransfer:
    """보낼 파일을 청크로 미리 분할해 들고 있으면서 진행 인덱스를 추적한다."""

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
        self.next_index = 0  # 다음에 보낼 청크 인덱스

    def has_next(self) -> bool:
        return self.next_index < self.total_chunks

    def peek_next(self) -> tuple[int, bytes] | None:
        """다음에 보낼 (index, data)를 돌려준다. 더 없으면 None."""
        if not self.has_next():
            return None
        return self.next_index, self.chunks[self.next_index]

    def advance(self) -> None:
        self.next_index += 1

    @property
    def done_chunks(self) -> int:
        return self.next_index


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

        RECEIVED_FILES_DIR.mkdir(parents=True, exist_ok=True)
        self.tmp_path = RECEIVED_FILES_DIR / f"{file_id}.part"
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
        final_path = _unique_path(RECEIVED_FILES_DIR / self.filename)
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
