#!/usr/bin/env bash
# DoChat macOS 빌드 스크립트: .app 번들 + 설치용 .pkg 생성
set -euo pipefail

cd "$(dirname "$0")/../.."

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install pyinstaller -q

rm -rf build_v2 dist_v2 DoChat.spec
python -m PyInstaller --windowed --name DoChat --icon assets/icon.icns --add-data "assets:assets" \
    --distpath dist_v2 --workpath build_v2 --noconfirm main.py

mkdir -p packaging/macos
pkgbuild --component dist_v2/DoChat.app \
    --install-location /Applications \
    --identifier com.dochat.app \
    --version 1.0.0 \
    packaging/macos/DoChat.pkg

echo ""
echo "=============================================="
echo "빌드 완료"
echo "  앱 번들:   dist_v2/DoChat.app"
echo "  설치 패키지: packaging/macos/DoChat.pkg"
echo "=============================================="
