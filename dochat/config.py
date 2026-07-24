"""DoChat 앱 전역 설정."""
from __future__ import annotations

import uuid
from pathlib import Path

APP_NAME = "DoChat"
APP_VERSION = "1.0.1"

try:
    # 패키징 스크립트/CI가 빌드 직전에 생성하는 파일. 소스에서 바로 실행하는
    # 개발 환경에는 없을 수 있으므로 없으면 조용히 None으로 둔다.
    # (구버전 캐시된 _build_info.py에는 BUILD_NUMBER가 없을 수도 있으므로
    # ImportError뿐 아니라 AttributeError도 함께 처리한다.)
    from dochat._build_info import BUILD_COMMIT, BUILD_DATE, BUILD_NUMBER
except (ImportError, AttributeError):
    BUILD_COMMIT = None
    BUILD_DATE = None
    BUILD_NUMBER = None


def get_version_string() -> str:
    """빌드 번호/커밋/날짜가 있으면 함께, 없으면 버전만 반환한다."""
    if BUILD_COMMIT:
        return f"{APP_VERSION} (build {BUILD_NUMBER}, {BUILD_COMMIT}, {BUILD_DATE})"
    return APP_VERSION

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

# 파일 전송 청크 크기(원본 바이트, base64/JSON/암호화 이전 기준).
# 청크 개수를 줄여 청크당 왕복 오버헤드(ACK 대기, 오브젝트 생성 비용)를 줄이되,
# 실제 전송되는 UDP 데이터그램 크기(base64 인코딩 + JSON 포장 + Fernet 암호화로
# 원본의 약 1.9배까지 부풀어 오름)가 OS의 단일 UDP 데이터그램 상한을 넘지 않도록
# 여유 있게 잡는다. 예) macOS는 기본적으로 net.inet.udp.maxdgram=9216바이트로 이보다
# 큰 데이터그램은 조용히 전송에 실패한다(재시도도 항상 실패해 전송이 멈춘다) —
# 실측(sysctl net.inet.udp.maxdgram, 실제 암호화 후 바이트 수 측정)으로 확인됨.
# FILE_CHUNK_SIZE=4096일 때 실제 전송 바이트는 약 7.7KB로 안전 마진을 확보한다.
FILE_CHUNK_SIZE = 4096

# 파일 전송 시 ACK를 기다리지 않고 동시에 "발송됨" 상태로 둘 수 있는 최대 청크 수
# (파이프라이닝 윈도우 크기). 클수록 처리량이 늘지만 재전송 시 낭비되는 대역폭도 커진다.
FILE_WINDOW_SIZE = 8

# 프레즌스(온라인 상태) 하트비트 주기
PRESENCE_INTERVAL_SEC = 5.0
PRESENCE_TIMEOUT_SEC = 15.0

# UDP 페이로드 암호화에 사용하는 기본 공유 비밀키(설정에서 별도로 지정하지 않은 경우 사용)
DEFAULT_NETWORK_KEY = "dochat-office-default-key-2026"
