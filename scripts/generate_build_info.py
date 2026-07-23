"""빌드 시점의 git 커밋/날짜 정보를 dochat/_build_info.py에 기록한다.

패키징 스크립트(build_macos.sh, build_windows.bat)와 GitHub Actions
워크플로우가 PyInstaller 실행 직전에 이 스크립트를 호출해서, 빌드마다
버전 표시가 최신 커밋을 반영하도록 한다. 소스에서 바로 실행하는
개발 환경에서는 이 파일이 없어도 dochat/config.py가 예외 없이
동작하도록 되어 있다 (버전 뒤 커밋 정보가 비어있을 뿐).
"""
from __future__ import annotations

import datetime
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def main() -> None:
    commit = _git("rev-parse", "--short", "HEAD") or "unknown"
    build_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    content = (
        '"""빌드 시점에 자동 생성되는 파일입니다. 직접 수정하지 마세요."""\n'
        f"BUILD_COMMIT = {commit!r}\n"
        f"BUILD_DATE = {build_date!r}\n"
    )

    out_path = ROOT / "dochat" / "_build_info.py"
    out_path.write_text(content, encoding="utf-8")
    print(f"build info written: commit={commit} date={build_date} -> {out_path}")


if __name__ == "__main__":
    main()
