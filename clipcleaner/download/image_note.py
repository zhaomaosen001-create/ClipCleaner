"""图文笔记下载与导出."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from clipcleaner.core.models import MediaInfo
from clipcleaner.utils import format_size, sanitize_filename

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 60
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _create_session(referer: str = "") -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
    )
    if referer:
        session.headers["Referer"] = referer
    else:
        session.headers["Referer"] = "https://www.xiaohongshu.com/"
    return session


def _guess_image_ext(url: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    if "gif" in ct:
        return ".gif"
    path = urlparse(url).path.lower()
    for ext in IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return ext
    return ".jpg"


def _build_note_folder(media: MediaInfo, base_dir: Path) -> Path:
    author = sanitize_filename(media.author or "未知作者", max_len=40)
    title = sanitize_filename(media.title or "图文笔记", max_len=60)
    note_id = (media.note_id or "")[:12]
    suffix = f"_{note_id}" if note_id else ""
    folder_name = f"{author}_{title}{suffix}"
    return base_dir / media.platform / folder_name


def _write_caption(path: Path, media: MediaInfo) -> None:
    """导出文案纯文本."""
    parts: List[str] = []
    if media.title:
        parts.append(media.title)
    if media.description:
        if parts:
            parts.append("")
        parts.append(media.description)
    path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")


def download_image_note(
    media: MediaInfo,
    output_dir: Path | str,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """下载图文笔记：图片 + 文案文本."""
    if not media.image_urls:
        raise RuntimeError("图文笔记没有可下载的图片")

    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    note_dir = _build_note_folder(media, base_dir)
    note_dir.mkdir(parents=True, exist_ok=True)

    session = _create_session(media.referer or media.source_url)
    total = len(media.image_urls)

    for idx, url in enumerate(media.image_urls, start=1):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("下载已取消")

        req_timeout = (CONNECT_TIMEOUT, READ_TIMEOUT)
        with session.get(url, stream=True, timeout=req_timeout) as resp:
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "")
            if "text/html" in ct.lower():
                raise RuntimeError(f"图片 {idx} 返回 HTML 而非图片内容")

            ext = _guess_image_ext(url, ct)
            dest = note_dir / f"{idx:03d}{ext}"
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if cancel_event and cancel_event.is_set():
                        raise InterruptedError("下载已取消")
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            if dest.stat().st_size < 512:
                dest.unlink(missing_ok=True)
                raise RuntimeError(f"图片 {idx} 文件过小，可能下载失败")

            if progress_callback:
                progress_callback(
                    idx,
                    total,
                    f"图片 {idx}/{total} ({format_size(downloaded)})",
                )

    _write_caption(note_dir / "caption.txt", media)

    logger.info("图文导出完成: %s (%d 张图)", note_dir, total)
    return note_dir
