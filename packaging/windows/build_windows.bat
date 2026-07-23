@echo off
REM DoChat Windows exe 빌드 스크립트
REM 반드시 Windows PC에서 실행해야 합니다 (PyInstaller는 크로스 컴파일을 지원하지 않음).
REM
REM 사용법:
REM   1) 이 저장소를 Windows PC로 복사합니다 (DoChat 폴더 전체).
REM   2) Python 3.10+ 를 설치합니다 (https://www.python.org/downloads/windows/).
REM   3) DoChat 폴더에서 이 스크립트를 더블클릭하거나 명령 프롬프트에서 실행합니다:
REM        packaging\windows\build_windows.bat
REM   4) 빌드가 끝나면 dist\DoChat\DoChat.exe 가 생성됩니다.

cd /d "%~dp0..\.."

python -m venv .venv_win
call .venv_win\Scripts\activate.bat

pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del DoChat.spec 2>nul

python -m PyInstaller --windowed --onefile --name DoChat --icon assets\icon.ico --add-data "assets;assets" --noconfirm main.py

echo.
echo ==============================================
echo 빌드 완료: dist\DoChat.exe (단일 실행 파일)
echo 이 파일 하나만 배포하면 됩니다.
echo ==============================================
pause
