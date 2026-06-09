"""通用工具函数."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """清理文件名中的非法字符."""
    name = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    name = re.sub(r"\s+", " ", name)
    if len(name) > max_len:
        name = name[:max_len]
    return name or f"video_{int(time.time())}"


def guess_filename_from_url(url: str) -> str:
    """从 URL 推断文件名."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    name = Path(path).name
    if name and "." in name:
        return sanitize_filename(name)
    return f"video_{int(time.time())}.mp4"


def guess_filename_from_headers(
    url: str, content_disposition: Optional[str]
) -> str:
    """从 Content-Disposition 或 URL 推断文件名."""
    if content_disposition:
        match = re.search(
            r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)',
            content_disposition,
            re.IGNORECASE,
        )
        if match:
            return sanitize_filename(unquote(match.group(1)))
    return guess_filename_from_url(url)


def format_size(num_bytes: int) -> str:
    """格式化字节大小."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def format_duration(seconds: float) -> str:
    """格式化时长."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
