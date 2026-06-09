#!/usr/bin/env bash
# 安装 AI 去水印依赖（PyTorch + E2FGVI 模型）
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 安装 AI 依赖..."
python3 -m pip install -r requirements-ai.txt

echo "==> 下载 E2FGVI 模型..."
python3 scripts/download_e2fgvi_model.py

echo "==> 克隆 E2FGVI 官方仓库..."
python3 - <<'PY'
from clipcleaner.e2fgvi_setup import clone_repo, default_repo_path
path = clone_repo(default_repo_path())
print(f"仓库路径: {path}")
PY

echo "==> AI 依赖安装完成"
