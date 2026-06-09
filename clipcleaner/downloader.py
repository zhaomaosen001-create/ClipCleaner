"""视频下载模块（线程安全、可取消）."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from clipcleaner.utils import (
    format_size,
    guess_filename_from_headers,
    guess_filename_from_url,
    sanitize_filename,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]  # downloaded, total, message

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 120
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2GB


class DownloadStatus(Enum):
    PENDING = "等待中"
    DOWNLOADING = "下载中"
    COMPLETED = "已完成"
    FAILED = "失败"
    CANCELLED = "已取消"


@dataclass
class DownloadTask:
    url: str
    save_dir: Path
    filename: str = ""
    title: str = ""
    author: str = ""
    platform: str = "direct"
    referer: str = ""
    status: DownloadStatus = DownloadStatus.PENDING
    progress: float = 0.0
    save_path: Optional[Path] = None
    error: str = ""
    total_bytes: int = 0
    downloaded_bytes: int = 0


def _create_session(timeout: int = 30) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
    )
    return session


def _validate_video_file(path: Path) -> None:
    """校验下载结果是否为有效视频文件."""
    size = path.stat().st_size
    if size < 2048:
        path.unlink(missing_ok=True)
        raise RuntimeError(
            f"下载文件过小（{size} 字节），链接可能不是视频直链。"
        )

    with open(path, "rb") as f:
        head = f.read(512)

    lower = head.lower()
    if b"<!doctype" in lower or b"<html" in lower or b"<head" in lower:
        path.unlink(missing_ok=True)
        raise RuntimeError(
            "下载内容是网页 HTML 而非视频文件。\n"
            "请使用平台分享链接，或先通过解析 API 获取视频直链。"
        )

    # mp4 / mov
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return
    # webm
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return
    # flv
    if head[:3] == b"FLV":
        return
    # mpeg-ts
    if head[0] == 0x47:
        return

    # 小文件且无法识别格式
    if size < 64 * 1024:
        path.unlink(missing_ok=True)
        raise RuntimeError("下载文件格式无法识别，可能不是有效视频。")


def _check_response_content_type(content_type: str, url: str) -> None:
    ct = (content_type or "").lower()
    if "text/html" in ct:
        raise RuntimeError(
            "该链接返回的是网页（HTML），不是视频文件。\n"
            f"链接: {url[:80]}...\n"
            "请配置解析 API 获取真实视频地址后再下载。"
        )
    if "application/json" in ct and "video" not in ct:
        raise RuntimeError("该链接返回的是 JSON 数据，不是视频文件。")


class DownloadWorker:
    """后台下载工作器，支持取消."""

    CHUNK_SIZE = 1024 * 64

    def __init__(
        self,
        task: DownloadTask,
        progress_callback: Optional[ProgressCallback] = None,
        finished_callback: Optional[Callable[[DownloadTask], None]] = None,
    ) -> None:
        self.task = task
        self.progress_callback = progress_callback
        self.finished_callback = finished_callback
        self._cancel_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _emit_progress(self, downloaded: int, total: int, msg: str = "") -> None:
        self.task.downloaded_bytes = downloaded
        self.task.total_bytes = total
        if total > 0:
            self.task.progress = min(100.0, downloaded / total * 100)
        else:
            # 无 Content-Length 时按已下载量显示估算进度
            self.task.progress = min(95.0, downloaded / (50 * 1024 * 1024) * 100)
        if self.progress_callback:
            self.progress_callback(downloaded, total, msg)

    def _run(self) -> None:
        try:
            self.task.status = DownloadStatus.DOWNLOADING
            save_path = download_video(
                self.task.url,
                self.task.save_dir,
                filename=self.task.filename or None,
                progress_callback=self._emit_progress,
                cancel_event=self._cancel_event,
                referer=self.task.referer or None,
            )
            if self.is_cancelled:
                self.task.status = DownloadStatus.CANCELLED
                if save_path.exists():
                    save_path.unlink(missing_ok=True)
            else:
                self.task.save_path = save_path
                self.task.status = DownloadStatus.COMPLETED
                self.task.progress = 100.0
        except Exception as exc:
            logger.exception("下载失败: %s", self.task.url)
            self.task.status = DownloadStatus.FAILED
            self.task.error = str(exc)
        finally:
            if self.finished_callback:
                self.finished_callback(self.task)


def download_video(
    url: str,
    save_path: Path | str,
    filename: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: int = READ_TIMEOUT,
    referer: Optional[str] = None,
) -> Path:
    """
    下载视频到指定路径。
    """
    save_path = Path(save_path)
    session = _create_session()
    if referer:
        session.headers["Referer"] = referer

    if save_path.suffix.lower() in (".mp4", ".webm", ".mov", ".avi", ".mkv", ".flv"):
        dest = save_path
        dest.parent.mkdir(parents=True, exist_ok=True)
    else:
        save_path.mkdir(parents=True, exist_ok=True)
        dest = None

    req_timeout = (CONNECT_TIMEOUT, timeout)

    with session.get(url, stream=True, timeout=req_timeout) as resp:
        resp.raise_for_status()
        _check_response_content_type(resp.headers.get("Content-Type", ""), url)

        if dest is None:
            if not filename:
                cd = resp.headers.get("Content-Disposition", "")
                filename = guess_filename_from_headers(url, cd)
                if not filename or filename == guess_filename_from_url(url):
                    filename = guess_filename_from_url(url)
            filename = sanitize_filename(filename)
            if not filename.lower().endswith((".mp4", ".webm", ".mov")):
                filename += ".mp4"
            dest = save_path / filename

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        start_time = time.time()
        stalled_since: Optional[float] = None

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=DownloadWorker.CHUNK_SIZE):
                if cancel_event and cancel_event.is_set():
                    logger.info("下载已取消: %s", url)
                    break

                if not chunk:
                    if total == 0:
                        now = time.time()
                        if stalled_since is None:
                            stalled_since = now
                        elif now - stalled_since > 30:
                            break
                    continue

                stalled_since = None
                f.write(chunk)
                downloaded += len(chunk)

                if downloaded > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("下载超过大小限制，可能不是有效视频直链")

                if progress_callback:
                    elapsed = time.time() - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    msg = f"{format_size(downloaded)}"
                    if total:
                        msg += f" / {format_size(total)} ({speed / 1024:.0f} KB/s)"
                    else:
                        msg += f" ({speed / 1024:.0f} KB/s)"
                    progress_callback(downloaded, total, msg)

        if cancel_event and cancel_event.is_set():
            if dest.exists():
                dest.unlink(missing_ok=True)
            raise InterruptedError("下载已取消")

    _validate_video_file(dest)
    logger.info("下载完成: %s -> %s (%s)", url, dest, format_size(dest.stat().st_size))
    return dest
