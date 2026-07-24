"""GitHub API로 최신 커밋을 조회해, 패키지된 배포본(exe/pkg)에서도
새 버전이 있는지 확인한다.

``dochat.update_checker``는 소스를 git으로 clone해서 실행하는 경우에만
``git fetch``/``git pull``로 업데이트를 확인/적용할 수 있다. PyInstaller 등으로
패키징된 실행 파일에는 git 저장소가 없으므로 그 방식이 통하지 않는다. 이
모듈은 그런 배포본에서도 GitHub REST API로 원격 저장소의 최신 커밋을 확인해,
빌드 시점에 내장된 커밋(``dochat.config.BUILD_COMMIT``)과 비교하는 용도다.

git이 없어도 동작하며(표준 라이브러리 ``urllib``만 사용, 추가 의존성 없음),
네트워크/API 오류는 예외를 던지지 않고 항상 dict로 감싸 반환한다. 실행 파일을
자동으로 내려받아 교체하지는 않으며, 새 버전 유무를 안내하고 다운로드 페이지로
안내하는 역할까지만 담당한다.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from dochat import config

REPO = "kms6402-collab/DoChat"
DEFAULT_BRANCH = "main"
API_URL = f"https://api.github.com/repos/{REPO}/commits/{DEFAULT_BRANCH}"
RELEASES_PAGE_URL = f"https://github.com/{REPO}/releases"
_TIMEOUT_SEC = 8


def check_for_new_release() -> dict:
    """GitHub API가 알려주는 최신 원격 커밋과, 현재 빌드에 내장된 커밋을 비교한다.

    반환값은 항상 dict:
    - 성공: {"has_update": bool, "local": str, "remote": str, "remote_short": str}
    - 실패: {"has_update": False, "error": str}
      (BUILD_COMMIT이 없는 개발 환경, 네트워크 오류, API 오류 등)
    """
    local_commit = getattr(config, "BUILD_COMMIT", None)
    if not local_commit:
        return {
            "has_update": False,
            "error": "이 빌드에는 커밋 정보가 포함되어 있지 않아 비교할 수 없습니다.",
        }

    try:
        req = urllib.request.Request(
            API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "DoChat-UpdateChecker",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        remote_full = data.get("sha", "")
        if not remote_full:
            return {"has_update": False, "error": "원격 커밋 정보를 확인할 수 없습니다."}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as exc:
        return {"has_update": False, "error": f"업데이트 확인 중 오류: {exc}"}

    remote_short = remote_full[:7]
    # BUILD_COMMIT은 보통 7~8자 짧은 해시, API가 주는 sha는 40자 전체 해시이므로
    # 접두사 비교로 같은 커밋인지 판단한다.
    same_commit = remote_full.startswith(local_commit) or local_commit.startswith(remote_full)
    has_update = not same_commit
    return {
        "has_update": has_update,
        "local": local_commit,
        "remote": remote_full,
        "remote_short": remote_short,
    }


def releases_page_url() -> str:
    """다운로드/릴리스 안내 페이지 URL을 반환한다."""
    return RELEASES_PAGE_URL
