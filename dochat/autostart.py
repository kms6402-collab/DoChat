"""Windows 로그인 시 DoChat 자동 시작 (레지스트리 Run 키 사용).

관리자 권한이 필요 없는 사용자별(HKEY_CURRENT_USER) 등록 방식이다.
Windows가 아니거나 패키징된 실행 파일이 아니면(예: 소스에서 python main.py로
직접 실행하는 경우) 아무 동작도 하지 않고 조용히 실패를 알린다 — 이 경우
"자동 시작"이 의미가 없기 때문이다(등록할 고정된 exe 경로가 없음).
"""
from __future__ import annotations

import sys

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "DoChat"


def is_supported() -> bool:
    """이 프로세스가 Windows용으로 패키징된(onefile) 실행 파일인지 확인한다."""
    return sys.platform.startswith("win") and getattr(sys, "frozen", False)


def is_enabled() -> bool:
    """현재 자동 시작이 등록되어 있는지 확인한다."""
    if not is_supported():
        return False
    import winreg  # Windows 전용 표준 라이브러리 모듈, 다른 OS에는 없음

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except (FileNotFoundError, OSError):
        return False


def set_enabled(enabled: bool) -> tuple[bool, str]:
    """자동 시작을 켜거나 끈다. (성공여부, 메시지) 반환. 예외를 던지지 않는다."""
    if not is_supported():
        return False, "이 실행 환경에서는 자동 시작 설정을 지원하지 않습니다."
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                exe_path = f'"{sys.executable}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True, "자동 시작 설정이 적용되었습니다."
    except OSError as exc:
        return False, f"자동 시작 설정에 실패했습니다: {exc}"
