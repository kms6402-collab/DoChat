"""DoChat 앱 전역 설정."""
from __future__ import annotations

import uuid
from pathlib import Path

APP_NAME = "DoChat"
APP_VERSION = "1.0.0"

# 로컬 데이터/수신 파일 저장 위치
APP_DIR = Path.home() / ".dochat"
DB_PATH = APP_DIR / "dochat.db"
RECEIVED_FILES_DIR = APP_DIR / "received"

APP_DIR.mkdir(parents=True, exist_ok=True)
RECEIVED_FILES_DIR.mkdir(parents=True, exist_ok=True)

# 이 인스턴스가 UDP를 수신 대기하는 기본 포트
DEFAULT_LISTEN_PORT = 47474

# 이 클라이언트를 구분하는 고유 ID (연락처 등록/그룹 멤버십에 사용)
_ID_FILE = APP_DIR / "client_id"
if _ID_FILE.exists():
    CLIENT_ID = _ID_FILE.read_text().strip()
else:
    CLIENT_ID = str(uuid.uuid4())
    _ID_FILE.write_text(CLIENT_ID)

# 신뢰성 계층(ACK/재전송) 파라미터
ACK_TIMEOUT_SEC = 1.0
MAX_RETRIES = 5

# 파일 전송 청크 크기 (LAN MTU 1500 고려, base64/JSON 오버헤드 감안한 여유값)
FILE_CHUNK_SIZE = 1200

# 프레즌스(온라인 상태) 하트비트 주기
PRESENCE_INTERVAL_SEC = 5.0
PRESENCE_TIMEOUT_SEC = 15.0
