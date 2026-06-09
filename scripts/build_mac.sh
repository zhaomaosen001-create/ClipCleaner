#!/usr/bin/env bash
# ClipCleaner macOS 打包：生成 .app、.zip、.dmg
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> 生成应用图标"
python3 scripts/generate_icon.py

echo "==> 安装依赖"
python3 -m pip install -q -r requirements.txt

echo "==> PyInstaller 打包 (.app)"
python3 -m PyInstaller build_mac.spec --noconfirm --clean

DIST="$ROOT/dist"
APP="$DIST/ClipCleaner.app"
if [[ ! -d "$APP" ]]; then
    echo "错误: 未找到 $APP"
    exit 1
fi

echo "==> 创建 ZIP 分发包"
cd "$DIST"
rm -f ClipCleaner-macOS.zip
ditto -c -k --sequesterRsrc --keepParent ClipCleaner.app ClipCleaner-macOS.zip

echo "==> 创建 DMG 安装镜像"
rm -f ClipCleaner-macOS.dmg
hdiutil create \
    -volname "ClipCleaner" \
    -srcfolder ClipCleaner.app \
    -ov \
    -format UDZO \
    ClipCleaner-macOS.dmg

echo ""
echo "打包完成:"
echo "  $DIST/ClipCleaner.app"
echo "  $DIST/ClipCleaner-macOS.zip"
echo "  $DIST/ClipCleaner-macOS.dmg"
echo ""
echo "其他 Mac 用户：打开 .dmg，将 ClipCleaner 拖入「应用程序」即可。"
