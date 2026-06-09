"""腾讯妙思 (admuse.qq.com) 浏览器自动化抓取 — 无需第三方 API."""

from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional, Tuple

from clipcleaner.api_resolver import VideoInfo
from clipcleaner.playwright_bootstrap import is_playwright_installed, launch_chromium
from clipcleaner.url_extractor import extract_admuse_video_id
from clipcleaner.url_finder import find_video_url

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]

# 网络响应中视为视频资源的 URL 特征
VIDEO_URL_HINTS = (
    ".mp4",
    ".m3u8",
    "stodownload",
    "finder.video.qq.com",
    "gtimg.com",
    "/video/",
    "videoplayback",
    "blob:",
)

SKIP_URL_MARKERS = (
    "picformat=",
    "wxampicformat=",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".js",
    ".css",
    "/favicon",
)


class AdmuseScraper:
    """使用 Playwright 无头浏览器打开妙思页面并拦截视频地址."""

    DEFAULT_TIMEOUT_MS = 60_000
    EXTRA_WAIT_MS = 3_000

    def __init__(self) -> None:
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        self._cancel_event.clear()

    @staticmethod
    def is_available() -> Tuple[bool, str]:
        if not is_playwright_installed():
            import sys

            return False, (
                "未安装 Playwright 包。\n"
                f"请运行: {sys.executable} -m pip install playwright"
            )
        return True, ""

    def parse(
        self,
        page_url: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> VideoInfo:
        ok, msg = self.is_available()
        if not ok:
            raise RuntimeError(msg)

        self.reset_cancel()

        def emit(pct: float, message: str) -> None:
            if progress_callback:
                progress_callback(pct, message)

        emit(5, "启动浏览器...")
        video_id = extract_admuse_video_id(page_url) or ""

        from playwright.sync_api import sync_playwright

        candidates: List[Tuple[int, str]] = []
        meta: dict = {"title": "", "author": ""}

        with sync_playwright() as pw:
            if self._cancel_event.is_set():
                raise InterruptedError("妙思解析已取消")

            browser = launch_chromium(pw, progress=lambda m: emit(8, m))
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
            page = context.new_page()

            def on_response(response) -> None:
                try:
                    self._handle_response(response, candidates, meta)
                except Exception as exc:
                    logger.debug("响应处理跳过: %s", exc)

            page.on("response", on_response)

            emit(15, "加载妙思页面...")
            target = self._normalize_page_url(page_url, video_id)
            logger.info("妙思页面: %s", target)

            try:
                page.goto(
                    target,
                    wait_until="domcontentloaded",
                    timeout=self.DEFAULT_TIMEOUT_MS,
                )
            except Exception as exc:
                logger.warning("页面加载超时或中断，继续尝试提取: %s", exc)

            if self._cancel_event.is_set():
                browser.close()
                raise InterruptedError("妙思解析已取消")

            emit(45, "等待视频资源加载...")
            page.wait_for_timeout(self.EXTRA_WAIT_MS)

            emit(60, "扫描页面视频元素...")
            self._extract_from_dom(page, candidates)

            emit(75, "读取页面元数据...")
            self._extract_page_meta(page, meta)

            browser.close()

        if self._cancel_event.is_set():
            raise InterruptedError("妙思解析已取消")

        video_url = self._pick_best_url(candidates)
        if not video_url:
            raise RuntimeError(
                "浏览器未能捕获妙思视频地址。\n"
                "可能原因：页面需登录、视频已下架、或网络超时。\n"
                "请确认链接可在浏览器中正常播放后重试。"
            )

        title = meta.get("title") or f"admuse_{video_id or 'video'}"
        author = meta.get("author") or "腾讯妙思"

        emit(100, "妙思视频地址已获取")
        return VideoInfo(
            title=title,
            author=author,
            cover_url=meta.get("cover", ""),
            video_url=video_url,
            platform="admuse",
        )

    @staticmethod
    def _normalize_page_url(page_url: str, video_id: str) -> str:
        """确保 hash 路由完整."""
        url = page_url.strip()
        if video_id and video_id not in url:
            base = url.split("#")[0].rstrip("/")
            return f"{base}#/idea/detail/video/{video_id}"
        if "#" not in url and video_id:
            return f"{url}#/idea/detail/video/{video_id}"
        return url

    def _handle_response(self, response, candidates: list, meta: dict) -> None:
        url = response.url
        lower = url.lower()

        if any(m in lower for m in SKIP_URL_MARKERS):
            return

        content_type = (response.headers.get("content-type") or "").lower()

        if any(h in lower for h in VIDEO_URL_HINTS):
            if "text/html" not in content_type:
                score = self._score_video_url(url)
                candidates.append((score, url))

        if "json" in content_type and any(
            k in lower for k in ("admuse", "muse", "idea", "video", "asset", "detail")
        ):
            try:
                body = response.json()
                found = find_video_url(body)
                if found:
                    candidates.append((self._score_video_url(found) + 20, found))
                if isinstance(body, dict):
                    title = body.get("title") or body.get("data", {}).get("title")
                    if title and not meta.get("title"):
                        meta["title"] = str(title)
            except Exception:
                pass

    @staticmethod
    def _score_video_url(url: str) -> int:
        lower = url.lower()
        score = 0
        if ".mp4" in lower:
            score += 40
        if "stodownload" in lower and "picformat" not in lower:
            score += 50
        if "m3u8" in lower:
            score += 30
        if "finder.video.qq.com" in lower:
            score += 35
        if lower.startswith("blob:"):
            score -= 30
        return score

    def _extract_from_dom(self, page, candidates: list) -> None:
        try:
            video_data = page.evaluate(
                """() => {
                const out = [];
                document.querySelectorAll('video').forEach(v => {
                    if (v.currentSrc) out.push(v.currentSrc);
                    if (v.src) out.push(v.src);
                });
                document.querySelectorAll('source').forEach(s => {
                    if (s.src) out.push(s.src);
                });
                return out;
            }"""
            )
            for u in video_data or []:
                if isinstance(u, str) and u.startswith("http"):
                    candidates.append((self._score_video_url(u), u))
        except Exception as exc:
            logger.debug("DOM 视频提取失败: %s", exc)

    def _extract_page_meta(self, page, meta: dict) -> None:
        try:
            title = page.title()
            if title and "妙思" not in title:
                meta["title"] = title
            elif not meta.get("title"):
                meta["title"] = title.replace("腾讯妙思", "").strip() or title

            extra = page.evaluate(
                """() => {
                const h1 = document.querySelector('h1');
                const author = document.querySelector('[class*="author"], [class*="nickname"]');
                return {
                    h1: h1 ? h1.innerText.trim() : '',
                    author: author ? author.innerText.trim() : '',
                };
            }"""
            )
            if extra.get("h1") and not meta.get("title"):
                meta["title"] = extra["h1"]
            if extra.get("author"):
                meta["author"] = extra["author"]
        except Exception as exc:
            logger.debug("页面元数据提取失败: %s", exc)

    def _pick_best_url(self, candidates: List[Tuple[int, str]]) -> Optional[str]:
        if not candidates:
            return None
        seen = set()
        unique = []
        for score, url in sorted(candidates, key=lambda x: -x[0]):
            if url not in seen and not url.startswith("blob:"):
                seen.add(url)
                unique.append((score, url))
        return unique[0][1] if unique else None


def parse_admuse_url(
    page_url: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> VideoInfo:
    """解析腾讯妙思分享链接."""
    return AdmuseScraper().parse(page_url, progress_callback)
