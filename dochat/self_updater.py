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


def _build_update_script(new_exe_path: Path, current_exe: Path) -> str:
    """새 exe로 교체·재실행하는 배치 스크립트 내용을 만든다.

    테스트를 위해 ``apply_self_update()``에서 분리된 순수 함수다. 아래 두
    가지 문제를 피하도록 신경 써서 작성했다 (실제 배포 후 "재시작하면
    스크립트 오류로 교체가 안 된다"는 버그의 원인으로 확인됨):

    1. PID가 아니라 이미지 이름(예: "DoChat.exe")으로 대기한다. PyInstaller
       onefile 부트로더는 버전/환경에 따라 부모/자식 프로세스 구조를 쓸 수
       있어, 이 파이썬 코드가 실행 중인 프로세스의 PID 하나만 감시하면 실제
       exe 파일을 잠그고 있는 다른 관련 프로세스가 남아있어도 놓칠 수 있다.
       이미지 이름 기준으로 "그 이름의 프로세스가 하나도 안 남을 때까지"
       기다리면 부모/자식 구조와 무관하게 안전하다.
    2. ``move`` 실패 시 재시도 + 로그 남기기. 백신 실시간 검사 등으로 파일이
       막 종료된 프로세스로부터 즉시 풀리지 않는 경우가 실무에서 흔하다.
       실패해도 조용히 다음 줄로 넘어가면 구버전이 그대로 남거나 실행 파일이
       사라진 상태가 될 수 있으므로, 재시도 후에도 실패하면 다운로드해둔
       새 exe를 지우지 않고 남겨두고 오류 로그를 남긴다.

    스크립트 내용은 인코딩 문제를 피하기 위해 전부 영어로만 작성한다
    (cmd.exe는 시스템 로캘 인코딩을 기대하는 경우가 많아, UTF-8로 저장된
    배치 파일에 한글이 섞이면 깨질 수 있다).
    """
    image_name = current_exe.name  # 보통 "DoChat.exe"
    lines = [
        "@echo off",
        "setlocal enabledelayedexpansion",
        f'set "IMAGE_NAME={image_name}"',
        f'set "NEW_EXE={new_exe_path}"',
        f'set "TARGET_EXE={current_exe}"',
        'set "LOG_FILE=%TEMP%\\dochat_update_error.log"',
        'set "WAIT_COUNT=0"',
        "",
        "rem Wait until no process with this image name is running (max ~60s).",
        ":wait_loop",
        'tasklist /FI "IMAGENAME eq %IMAGE_NAME%" 2>NUL | find /I "%IMAGE_NAME%" >NUL',
        "if not errorlevel 1 (",
        "    set /a WAIT_COUNT+=1",
        "    if !WAIT_COUNT! GEQ 60 (",
        '        echo Timed out waiting for %IMAGE_NAME% to exit. >> "%LOG_FILE%"',
        "        goto :eof",
        "    )",
        "    timeout /t 1 /nobreak >NUL",
        "    goto wait_loop",
        ")",
        "",
        "rem Replace the exe, retrying a few times in case the file handle",
        "rem has not been released yet.",
        'set "MOVE_TRIES=0"',
        ":move_retry",
        'move /Y "%NEW_EXE%" "%TARGET_EXE%" >NUL 2>>"%LOG_FILE%"',
        "if errorlevel 1 (",
        "    set /a MOVE_TRIES+=1",
        "    if !MOVE_TRIES! GEQ 5 (",
        "        echo Failed to replace %TARGET_EXE% after !MOVE_TRIES! attempts. "
        'New file kept at %NEW_EXE% >> "%LOG_FILE%"',
        "        goto :eof",
        "    )",
        "    timeout /t 2 /nobreak >NUL",
        "    goto move_retry",
        ")",
        "",
        'start "" "%TARGET_EXE%"',
        "timeout /t 1 /nobreak >NUL",
        'del "%~f0"',
        "",
    ]
    return "\r\n".join(lines)


def _verify_downloaded_exe(path: Path, expected_size: int | None) -> str | None:
    """다운로드된 exe가 온전한지 검증한다. 문제가 있으면 오류 메시지를,
    정상이면 ``None``을 반환한다.

    "Failed to load Python DLL" 팝업과 함께 재시작에 실패하던 문제의
    원인이었다: 다운로드가 중간에 끊겨도 ``urlopen().read()``가 빈 바이트를
    반환하면 정상 종료로 오인해, 잘리거나 손상된 exe를 그대로 기존 실행
    파일 자리에 옮겨 심어버렸다. 옮기기 전에 반드시 다음을 확인한다:

    1. 파일 크기가 GitHub 릴리스 자산의 크기(``expected_size``)와 정확히
       일치하는지 (알 수 없으면 이 검사는 건너뜀)
    2. Windows PE 실행 파일의 매직 바이트("MZ")로 시작하는지 — HTML 오류
       페이지 등 완전히 다른 내용이 저장된 경우까지 잡아낸다.
    """
    if not path.exists():
        return "다운로드한 파일을 찾을 수 없습니다."

    actual_size = path.stat().st_size
    if actual_size == 0:
        return "다운로드한 파일이 비어 있습니다."
    if expected_size and actual_size != expected_size:
        return (
            f"다운로드가 손상되었습니다 (예상 크기 {expected_size:,}바이트, "
            f"실제 {actual_size:,}바이트). 네트워크 연결을 확인한 뒤 다시 시도해 주세요."
        )

    try:
        with open(path, "rb") as f:
            header = f.read(2)
    except OSError as exc:
        return f"다운로드한 파일을 확인하지 못했습니다: {exc}"
    if header != b"MZ":
        return "다운로드한 파일이 올바른 실행 파일이 아닙니다. 다시 시도해 주세요."

    return None


def apply_self_update(download_url: str, expected_size: int | None = None) -> tuple[bool, str]:
    """새 exe를 내려받아 현재 실행 파일을 자동으로 교체·재시작하도록 예약한다.

    성공 시 True를 반환하며, 호출한 쪽은 곧이어 앱을 종료해야 한다
    (교체 스크립트가 현재 프로세스 종료를 기다리기 때문).

    ``expected_size``는 ``check_for_self_update()``가 반환한 GitHub 릴리스
    자산의 크기(바이트)다. 넘겨주면 다운로드 무결성 검증에 사용된다
    (``_verify_downloaded_exe`` 참고) — 이게 없으면 네트워크가 중간에
    끊겨도 조용히 손상된 exe로 교체해버려 "Failed to load Python DLL"
    오류로 재시작에 실패하는 문제가 있었다.
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
            # 서버가 알려준 Content-Length와 실제로 받은 바이트 수를 직접
            # 대조한다 (expected_size가 없거나 부정확한 경우에 대비한
            # 2차 방어선).
            content_length = resp.headers.get("Content-Length")
            expected_from_header = int(content_length) if content_length and content_length.isdigit() else None

            written = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)

        if expected_from_header is not None and written != expected_from_header:
            new_exe_path.unlink(missing_ok=True)
            return False, (
                f"다운로드가 중간에 끊겼습니다 (받은 크기 {written:,}바이트 / "
                f"예상 {expected_from_header:,}바이트). 다시 시도해 주세요."
            )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        new_exe_path.unlink(missing_ok=True)
        return False, f"새 버전 다운로드에 실패했습니다: {exc}"

    verify_error = _verify_downloaded_exe(new_exe_path, expected_size)
    if verify_error is not None:
        new_exe_path.unlink(missing_ok=True)
        return False, verify_error

    bat_content = _build_update_script(new_exe_path, current_exe)
    try:
        # cmd.exe는 시스템 로캘(예: 한국어 Windows의 CP949) 인코딩을 기대하는
        # 경우가 많아, 배치 파일에 한글이 섞이면 깨질 수 있다. 스크립트 내용을
        # 전부 영어로만 작성해 인코딩 문제를 원천 차단하고, ASCII로 안전하게 쓴다.
        bat_path.write_text(bat_content, encoding="ascii")
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
