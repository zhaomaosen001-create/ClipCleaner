#!/usr/bin/env bash
# 推送代码到 GitHub 并提示触发 Windows 自动打包
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REPO_URL="${1:-}"
if [[ -z "$REPO_URL" ]]; then
    echo "用法:"
    echo "  ./scripts/setup_github.sh https://github.com/你的用户名/ClipCleaner.git"
    echo ""
    echo "步骤:"
    echo "  1. 打开 https://github.com/new 新建空仓库（不要勾选 README）"
    echo "  2. 复制仓库 HTTPS 地址，执行本脚本"
    exit 1
fi

if git remote get-url origin &>/dev/null; then
    git remote set-url origin "$REPO_URL"
else
    git remote add origin "$REPO_URL"
fi

echo "==> 推送到 GitHub"
git push -u origin main

REPO_SLUG="${REPO_URL%.git}"
REPO_SLUG="${REPO_SLUG#https://github.com/}"
ACTIONS_URL="https://github.com/${REPO_SLUG}/actions/workflows/build-release.yml"

echo ""
echo "推送完成。"
echo ""
echo "触发 Windows 自动打包:"
echo "  1. 打开 ${ACTIONS_URL}"
echo "  2. 点击 Run workflow"
echo "  3. platform 选择 windows"
echo "  4. 运行完成后在 Artifacts 下载 ClipCleaner-Windows"
