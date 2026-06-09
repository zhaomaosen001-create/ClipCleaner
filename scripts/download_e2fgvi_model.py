#!/usr/bin/env python3
"""下载 E2FGVI-HQ 模型到 ClipCleaner 配置目录."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clipcleaner.model_setup import (  # noqa: E402
    default_model_path,
    download_model,
    is_valid_model_file,
)


def main() -> int:
    dest = default_model_path()
    print(f"目标路径: {dest}")
    if is_valid_model_file(dest):
        print("模型已存在，无需重复下载。")
        return 0

    def on_progress(pct: float, msg: str) -> None:
        print(f"\r[{pct:5.1f}%] {msg}", end="", flush=True)

    try:
        download_model(dest, progress_callback=on_progress)
        print("\n下载完成。")
        return 0
    except Exception as exc:
        print(f"\n下载失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
