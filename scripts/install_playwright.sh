#!/bin/bash
# 安装 Playwright 及 Chromium 浏览器（妙思抓取必需）
set -e
PY="${PYTHON:-python3}"
echo "==> 使用 Python: $PY"
"$PY" -m pip install playwright
echo "==> 下载 Chromium（约 100MB，请耐心等待）..."
"$PY" -m playwright install chromium
echo "==> 完成！可运行: $PY main.py 或 $PY scripts/admuse_download.py"
