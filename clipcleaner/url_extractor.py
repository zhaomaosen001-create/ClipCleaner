"""从用户粘贴内容中提取分享链接."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

# 从混合文本中提取 http(s) 链接（含 # 路由）
_HTTP_URL_RE = re.compile(
    r"https?://[^\s<>\"{}|\\^`\[\]\u3000-\u303f\uff01-\uff60#]*(?:#[^\s<>\"{}|\\^`\[\]]*)?",
    re.IGNORECASE,
)

WEIXIN_HOST_PATTERNS = (
    r"channels\.weixin\.qq\.com",
    r"weixin\.qq\.com",
    r"wxaurl\.cn",
    r"wx\.qq\.com",
    r"mp\.weixin\.qq\.com",
)

PLATFORM_URL_HINTS = {
    "weixin": WEIXIN_HOST_PATTERNS,
    "douyin": (r"douyin\.com", r"iesdouyin\.com", r"v\.douyin\.com"),
    "xiaohongshu": (r"xiaohongshu\.com", r"xhslink\.com"),
    "kuaishou": (r"kuaishou\.com", r"v\.kuaishou\.com"),
    "bilibili": (r"bilibili\.com", r"b23\.tv"),
    "admuse": (r"admuse\.qq\.com",),
}

# 可直接下载的 CDN 特征
DIRECT_VIDEO_CDN_HINTS = (
    "finder.video.qq.com/stodownload",
    "bilivideo.com",
    "upos-sz",
    "douyinvod.com",
    "snssdk.com/aweme/v1/play",
    "gtimg.com/video",
    "xhscdn.com",
    "kuaishou.com/short-video",
    ".m3u8",
)


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?)]}」』》）")


def _match_platform(url: str, patterns: tuple) -> bool:
    return any(re.search(p, url, re.IGNORECASE) for p in patterns)


def extract_urls(text: str) -> List[str]:
    if not text:
        return []
    urls = [_clean_url(u) for u in _HTTP_URL_RE.findall(text)]
    seen = set()
    result = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def pick_best_url(urls: List[str], prefer_platform: Optional[str] = None) -> Optional[str]:
    if not urls:
        return None

    if prefer_platform and prefer_platform in PLATFORM_URL_HINTS:
        patterns = PLATFORM_URL_HINTS[prefer_platform]
        for u in urls:
            if _match_platform(u, patterns):
                return u

    for _platform, patterns in PLATFORM_URL_HINTS.items():
        for u in urls:
            if _match_platform(u, patterns):
                return u

    return urls[0]


def is_spa_page_url(url: str) -> bool:
    """是否为前端 SPA 页面链接（非视频直链）."""
    lower = url.lower()
    if "admuse.qq.com" in lower:
        return True
    if "#/" in url and re.search(r"/(video|idea|detail|work)/", url, re.I):
        return True
    parsed = urlparse(url)
    frag = parsed.fragment or ""
    if frag and re.search(r"(video|idea|detail)/", frag, re.I):
        return True
    return False


def is_third_party_vod_page(url: str) -> bool:
    """是否为第三方点播/播放页（非已知短视频平台）."""
    from clipcleaner.api_resolver import detect_platform

    lower = url.lower()
    if detect_platform(url):
        return False
    path = urlparse(url).path.lower()
    if re.search(r"/(?:vods?|watch|play|detail|share)/", path):
        return True
    if any(hint in lower for hint in ("beabox", ".shop/vod")):
        return True
    return False


def is_likely_direct_video(url: str) -> bool:
    """判断是否像可直接下载的视频 CDN 链接."""
    lower = url.lower()
    path = urlparse(url).path.lower()
    if re.search(r"\.(mp4|m3u8|webm|mov|avi|flv|mkv)(\?|$)", path, re.I):
        return True
    return any(hint in lower for hint in DIRECT_VIDEO_CDN_HINTS)


def extract_admuse_video_id(url: str) -> Optional[str]:
    """从妙思链接 hash 路由提取视频 ID."""
    m = re.search(r"/idea/detail/video/(\d+)", url, re.I)
    if m:
        return m.group(1)
    m = re.search(r"video/(\d+)", url, re.I)
    return m.group(1) if m else None


def normalize_input(raw: str) -> Tuple[str, str]:
    original = raw.strip()
    if not original:
        raise ValueError("链接不能为空")

    urls = extract_urls(original)
    if urls:
        share_url = pick_best_url(urls) or urls[0]
        return share_url, original

    candidate = original
    if not candidate.startswith(("http://", "https://")):
        if re.search(
            r"(channels\.weixin|weixin\.qq|douyin|xiaohongshu|bilibili|kuaishou|admuse)",
            candidate,
            re.I,
        ):
            candidate = "https://" + candidate.lstrip("/")
            return _clean_url(candidate), original
        raise ValueError(
            "未识别到有效链接。\n"
            "请粘贴包含 https:// 的分享链接，或直接粘贴视频号分享全文。"
        )

    return _clean_url(candidate), original


def is_weixin_share(url: str, original_text: str = "") -> bool:
    for target in (url, original_text):
        if target and _match_platform(target, WEIXIN_HOST_PATTERNS):
            return True
        if target and re.search(r"视频号|finderInline|sph/", target, re.I):
            return True
    return False
