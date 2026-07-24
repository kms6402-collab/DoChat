"""Windows 단일 파일(exe) 배포본의 자체 업데이트(다운로드 + 자동 교체 + 재시작).

동작 방식:
1. GitHub Releases의 "latest" 릴리스에서 고정된 이름("DoChat.exe") 자산을 찾는다.
2. 그 릴리스 태그(예: "v1.0.1")를 ``dochat.config.APP_VERSION``과 비교한다.
3. 새 버전이 있으면 임시 폴더에 새 exe를 내려받는다.
4. 실행 중인 exe는 자기 자신을 직접 덮어쓸 수 없으므로, 별도의 배치(.bat)
   스크립트를 생성해 분리된 프로세스로 띄운다. 그 배치 스크립트가 현재
   프로세스가 완전히 종료될 때까지 기다렸다가 새 exe로 교체하고 재실행한다.

macOS(.pkg)나 git 소스 실행 환경에서는 지원하지 않는다 (``is_supported()``가
False를 반환하며, 그 경우 UI는 기존 릴리스 페이지 안내로 폴백해야 한다).
모든 실패는 예외를 던지지 않고 항상 값으로 반환한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from dochat import config

REPO = "kms6402-collab/DoChat"
API_LATEST_RELEASE = f"https://api.github.com/repos/{REPO}/releases/latest"
WINDOWS_ASSET_NAME = "DoChat.exe"
_TIMEOUT_SEC = 10


def is_supported() -> bool:
    """이 프로세스가 Windows용으로 패키징된(onefile) 실행 파일인지 확인한다."""
    return sys.platform.startswith("win") and getattr(sys, "frozen", False)


def _parse_version(text: str) -> tuple[int, ...]:
    """"v1.2.3" / "1.2.3" 같은 문자열을 비교 가능한 정수 튜플로 바꾼다."""
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def _get_latest_release() -> dict:
    """GitHub의 최신 릴리스 정보(dict)를 가져온다. 실패 시 {"error": ...}."""
    try:
        req = urllib.request.Request(
            API_LATEST_RELEASE,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "DoChat-SelfUpdater"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as exc:
        return {"error": f"릴리스 정보를 가져오지 못했습니다: {exc}"}

    tag = data.get("tag_name") or ""
    assets = data.get("assets") or []
    asset = next(
        (a for a in assets if (a.get("name") or "").lower() == WINDOWS_ASSET_NAME.lower()),
        None,
    )
    if not tag or asset is None:
        return {"error": "릴리스에서 Windows 실행 파일을 찾을 수 없습니다."}

    return {
        "tag": tag,
        "download_url": asset.get("browser_download_url"),
        "size": asset.get("size", 0),
    }


def check_for_self_update() -> dict:
    """최신 릴리스와 현재 버전을 비교한다.

    반환값은 항상 dict:
    - {"has_update": bool, "remote_tag": str, "download_url": str, "size": int}
    - 실패 시: {"has_update": False, "error": str}
    """
    if not is_supported():
        return {"has_update": False, "error": "이 실행 환경에서는 자동 업데이트를 지원하지 않습니다."}

    info = _get_latest_release()
    if "error" in info:
        return {"has_update": False, "error": info["error"]}

    remote_version = _parse_version(info["tag"])
    local_version = _parse_version(config.APP_VERSION)
    has_update = remote_version > local_version

    return {
        "has_update": has_update,
        "remote_tag": info["tag"],
        "download_url": info["download_url"],
        "size": info.get("size", 0),
    }


def apply_self_update(download_url: str) -> tuple[bool, str]:
    """새 exe를 내려받아 현재 실행 파일을 자동으로 교체·재시작하도록 예약한다.

    성공 시 True를 반환하며, 호출한 쪽은 곧이어 앱을 종료해야 한다
    (교체 스크립트가 현재 프로세스 종료를 기다리기 때문).
    """
    if not is_supported():
        return False, "이 실행 환경에서는 자동 업데이트를 지원하지 않습니다."
    if not download_url:
        return False, "다운로드 주소를 확인할 수 없습니다."

    current_exe = Path(sys.executable).resolve()
    temp_dir = Path(tempfile.gettempdir())
    token = uuid.uuid4().hex
    new_exe_path = temp_dir / f"DoChat_update_{token}.exe"
    bat_path = temp_dir / f"dochat_update_{token}.bat"

    try:
        req = urllib.request.Request(download_url, headers={"User-Agent": "DoChat-SelfUpdater"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(new_exe_path, "wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        new_exe_path.unlink(missing_ok=True)
        return False, f"새 버전 다운로드에 실패했습니다: {exc}"

    if not new_exe_path.exists() or new_exe_path.stat().st_size == 0:
        new_exe_path.unlink(missing_ok=True)
        return False, "다운로드한 파일이 비어 있습니다."

    pid = os.getpid()
    # 현재 프로세스(PID)가 완전히 종료될 때까지 기다린 뒤 exe를 교체하고
    # 재실행한다. tasklist로 해당 PID가 더 이상 목록에 없을 때까지 반복 확인.
    bat_content = (
        "@echo off\r\n"
        ":wait_loop\r\n"
        f'tasklist /FI "PID eq {pid}" 2^>NUL | find "{pid}" >NUL\r\n'
        "if not errorlevel 1 (\r\n"
        "    timeout /t 1 /nobreak >NUL\r\n"
        "    goto wait_loop\r\n"
        ")\r\n"
        f'move /Y "{new_exe_path}" "{current_exe}" >NUL\r\n'
        f'start "" "{current_exe}"\r\n'
        'del "%~f0"\r\n'
    )
    try:
        bat_path.write_text(bat_content, encoding="utf-8")
    except OSError as exc:
        new_exe_path.unlink(missing_ok=True)
        return False, f"업데이트 스크립트를 준비하지 못했습니다: {exc}"

    try:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            ["cmd", "/c", "start", "/min", "", str(bat_path)],
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as exc:
        new_exe_path.unlink(missing_ok=True)
        bat_path.unlink(missing_ok=True)
        return False, f"업데이트 적용을 시작하지 못했습니다: {exc}"

    return True, "업데이트를 내려받았습니다. 잠시 후 DoChat이 자동으로 재시작됩니다."
