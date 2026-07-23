"""git 소스 배포(clone 후 ``python main.py`` 직접 실행) 환경에서의 업데이트 확인/적용.

패키징된 실행 파일(exe/pkg) 배포본에는 해당되지 않으며, 프로젝트 루트가
git 작업 트리인 경우에만 의미 있는 결과를 반환한다. 네트워크/git 오류는
예외로 던지지 않고 항상 dict/tuple로 감싸 돌려주어 UI에서 그대로 안내
메시지로 보여줄 수 있게 한다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# main.py가 위치한 프로젝트 루트 (dochat/update_checker.py 기준 한 단계 위)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

_TIMEOUT_SEC = 15
_QUICK_TIMEOUT_SEC = 5
_CANDIDATE_BRANCHES = ("main", "master")


def _run(args: list[str], timeout: int = _TIMEOUT_SEC) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def is_git_checkout() -> bool:
    """프로젝트 루트가 git 작업 트리인지 확인한다."""
    try:
        result = _run(["rev-parse", "--is-inside-work-tree"], timeout=_QUICK_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _detect_remote_branch() -> str | None:
    """origin/main 또는 origin/master 중 실제로 존재하는 브랜치 이름을 반환한다."""
    for branch in _CANDIDATE_BRANCHES:
        try:
            result = _run(["rev-parse", "--verify", f"origin/{branch}"])
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode == 0:
            return branch
    return None


def check_for_updates() -> dict:
    """``git fetch origin`` 후 로컬 HEAD와 원격 브랜치를 비교한다.

    반환값은 항상 dict이다.
    - 성공: {"has_update": bool, "local": str, "remote": str, "behind_count": int, "branch": str}
    - 실패(git 없음/원격 접근 실패 등): {"has_update": False, "error": str}
    """
    if not is_git_checkout():
        return {"has_update": False, "error": "git 저장소가 아닙니다."}

    try:
        fetch_result = _run(["fetch", "origin"])
        if fetch_result.returncode != 0:
            return {"has_update": False, "error": fetch_result.stderr.strip() or "git fetch에 실패했습니다."}

        branch = _detect_remote_branch()
        if branch is None:
            return {"has_update": False, "error": "원격 브랜치(main/master)를 찾을 수 없습니다."}

        local_result = _run(["rev-parse", "HEAD"])
        remote_result = _run(["rev-parse", f"origin/{branch}"])
        if local_result.returncode != 0 or remote_result.returncode != 0:
            return {"has_update": False, "error": "커밋 정보를 확인할 수 없습니다."}

        local_full = local_result.stdout.strip()
        remote_full = remote_result.stdout.strip()

        count_result = _run(["rev-list", "--count", f"{local_full}..{remote_full}"])
        behind_count = 0
        if count_result.returncode == 0 and count_result.stdout.strip().isdigit():
            behind_count = int(count_result.stdout.strip())

        return {
            "has_update": local_full != remote_full and behind_count > 0,
            "local": local_full[:8],
            "remote": remote_full[:8],
            "behind_count": behind_count,
            "branch": branch,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"has_update": False, "error": str(exc)}


def apply_update() -> tuple[bool, str]:
    """감지된 원격 브랜치를 ``git pull``로 받아온다.

    로컬에 커밋되지 않은 변경사항이 있어 pull이 막히는 경우를 포함해, git이
    돌려준 오류 메시지를 그대로 노출한다. stash/reset 등 파괴적인 동작은
    수행하지 않는다.
    """
    if not is_git_checkout():
        return False, "git 저장소가 아니라 업데이트를 적용할 수 없습니다."

    try:
        branch = _detect_remote_branch() or "main"
        result = _run(["pull", "origin", branch])
        if result.returncode == 0:
            return True, "업데이트 완료. 프로그램을 재시작해 주세요."
        error_message = result.stderr.strip() or result.stdout.strip() or "알 수 없는 오류로 업데이트에 실패했습니다."
        return False, error_message
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
