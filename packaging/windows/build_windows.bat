@echo off
REM DoChat Windows exe 빌드 스크립트 (단일 파일)
REM 반드시 Windows PC에서 실행해야 합니다 (PyInstaller는 크로스 컴파일을 지원하지 않음).
REM
REM 사용법:
REM   1) 이 저장소를 Windows PC로 복사합니다 (DoChat 폴더 전체).
REM   2) Python 3.10+ 를 설치합니다 (https://www.python.org/downloads/windows/).
REM   3) DoChat 폴더에서 이 스크립트를 더블클릭하거나 명령 프롬프트에서 실행합니다:
REM        packaging\windows\build_windows.bat
REM   4) 빌드가 끝나면 dist\DoChat.exe 가 생성됩니다 (단일 실행 파일).
REM
REM 참고: 앱 안의 "업데이트 확인" 기능은 GitHub 릴리스 자산 이름이
REM "DoChat.exe"로 고정되어 있다고 가정하고 자동 업데이트를 수행합니다.
REM 정식 배포는 GitHub Actions(.github/workflows/build-windows.yml)로 태그를
REM 푸시했을 때 자동으로 이 이름으로 릴리스에 올라갑니다.
REM (그래서 dist\DoChat.exe 자체의 이름은 바꾸지 않고, 버전이 표시된 복사본을
REM  하나 더 만들어 로컬에서 어떤 버전을 빌드했는지 구분하기 쉽게 한다.)

cd /d "%~dp0..\.."

python -m venv .venv_win
call .venv_win\Scripts\activate.bat

pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

python scripts\generate_build_info.py

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del DoChat.spec 2>nul

python -m PyInstaller --windowed --onefile --name DoChat --icon assets\icon.ico --add-data "assets;assets" --noconfirm main.py

for /f "delims=" %%v in ('python -c "import dochat.config as c; print(c.APP_VERSION)"') do set APP_VERSION=%%v
copy /Y dist\DoChat.exe "dist\DoChat_v%APP_VERSION%.exe" >nul

echo.
echo ==============================================
echo 빌드 완료: dist\DoChat.exe (단일 실행 파일)
echo 버전 표시 사본: dist\DoChat_v%APP_VERSION%.exe
echo GitHub Release/자동 업데이트에는 dist\DoChat.exe를 그대로 쓰세요
echo (자동 업데이트 기능이 파일명 "DoChat.exe"를 그대로 찾습니다).
echo ==============================================
pause
