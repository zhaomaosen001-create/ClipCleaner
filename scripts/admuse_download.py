#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯妙思视频抓取脚本（独立命令行）

用法:
  python scripts/admuse_download.py "https://admuse.qq.com/#/idea/detail/video/105872194371"
  python scripts/admuse_download.py "妙思链接" --output ~/Downloads

首次使用请安装:
  pip install playwright
  playwright install chromium
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="腾讯妙思视频地址抓取")
    parser.add_argument("url", help="妙思分享链接（含 #/idea/detail/video/...）")
    parser.add_argument(
        "-o", "--output",
        help="下载保存目录（仅 --download 时有效）",
        default="",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="解析后直接下载视频",
    )
    args = parser.parse_args()

    from clipcleaner.admuse_scraper import AdmuseScraper, parse_admuse_url

    ok, msg = AdmuseScraper.is_available()
    if not ok:
        print(f"错误: {msg}")
        return 1

    def progress(pct: float, text: str) -> None:
        print(f"[{pct:3.0f}%] {text}")

    try:
        info = parse_admuse_url(args.url, progress_callback=progress)
    except Exception as exc:
        print(f"解析失败: {exc}")
        return 1

    print("\n=== 解析结果 ===")
    print(f"标题: {info.title}")
    print(f"作者: {info.author}")
    print(f"平台: {info.platform}")
    print(f"视频直链:\n{info.video_url}")

    if args.download:
        from clipcleaner.config import ConfigManager
        from clipcleaner.downloader import download_video

        out = Path(args.output) if args.output else ConfigManager().config.output_path
        out.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in info.title)
        dest = download_video(
            info.video_url,
            out,
            filename=f"{safe_name[:80]}.mp4",
            progress_callback=lambda d, t, m: print(f"下载: {m}"),
        )
        print(f"\n已保存: {dest}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
