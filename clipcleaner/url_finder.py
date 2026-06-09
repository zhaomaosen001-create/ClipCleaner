"""从任意 JSON 响应中递归提取视频直链."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse

# 常见视频链接字段名（优先级从高到低）
VIDEO_KEY_NAMES = (
    "nwm_video_url",
    "nwm_video_url_hq",
    "nwm_video_url_list",
    "nwm_video_url_HQ",
    "no_watermark_url",
    "nowm_video_url",
    "download_url",
    "video_backup",  # 视频号等多清晰度备份列表
    "video_url",
    "videourl",
    "videoUrl",
    "play_url",
    "playUrl",
    "play_addr",
    "playAddr",
    "masterUrl",
    "master_url",
    "srcNoMark",
    "url_list",
    "urlList",
    "durl",
    "play",
    "url",
    "src",
    "source",
    "link",
    "mp4",
    "m3u8",
    "stream_url",
    "streamUrl",
    "wm_video_url",
)

# 明显非视频资源的字段名片段
NON_VIDEO_KEY_FRAGMENTS = (
    "cover",
    "avatar",
    "thumb",
    "thumbnail",
    "poster",
    "icon",
    "image",
    "pic",
    "photo",
    "logo",
    "banner",
    "music",
    "audio",
)

VIDEO_EXT_PATTERN = re.compile(
    r"\.(mp4|m3u8|webm|mov|flv|mkv|avi|ts)(\?|$|#)",
    re.IGNORECASE,
)

VIDEO_HOST_HINTS = (
    "aweme",
    "douyin",
    "snssdk",
    "tiktok",
    "bilivideo",
    "hdslb",
    "kuaishou",
    "xhscdn",
    "weixin",
    "finder.video.qq.com",
    "stodownload",  # 微信视频号 CDN
    "qq.com",
    "/play/",
    "stream",
)

# URL 路径/参数中的非视频特征（避免 picformat 误伤）
NON_VIDEO_URL_MARKERS = (
    "picformat=",
    "wxampicformat=",
    "/finderhead/",
    "qlogo.cn",
    "avatar",
    "sns-subtitle",
    "/subtitle/",
)

IMAGE_EXT_PATTERN = re.compile(
    r"\.(jpe?g|png|webp|gif|bmp|heic|avif)(\?|$|#)",
    re.IGNORECASE,
)


def _normalize_url(url: str) -> str:
    url = url.strip().replace("\\/", "/")
    if url.startswith("//"):
        url = "https:" + url
    return url.replace("playwm", "play").replace("/playwm/", "/play/")


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and (
        value.startswith("http://") or value.startswith("https://") or value.startswith("//")
    )


def _is_likely_cover_or_avatar_url(url: str) -> bool:
    lower = url.lower()
    return any(marker in lower for marker in NON_VIDEO_URL_MARKERS)


def _is_likely_page_url(url: str) -> bool:
    """点播/播放页链接（含 /vods/、/watch/ 等），不是 CDN 直链."""
    if not _is_http_url(url):
        return False
    if VIDEO_EXT_PATTERN.search(url):
        return False
    path = urlparse(url).path.lower()
    return bool(
        re.search(
            r"/(?:vods?|watch|play|video|detail|share)/[^/]+/?$",
            path,
            re.IGNORECASE,
        )
    )


def _looks_like_video_url(url: str) -> bool:
    if not _is_http_url(url):
        return False
    lower = url.lower()
    if _is_likely_cover_or_avatar_url(url):
        return False
    if IMAGE_EXT_PATTERN.search(lower):
        return False
    if _is_likely_page_url(url):
        return False
    if VIDEO_EXT_PATTERN.search(lower):
        return True
    if any(hint in lower for hint in VIDEO_HOST_HINTS):
        return True
    return False


def _key_priority(key: str) -> int:
    key_lower = key.lower()
    for i, name in enumerate(VIDEO_KEY_NAMES):
        if key_lower == name.lower():
            return len(VIDEO_KEY_NAMES) - i
    # 部分匹配
    score = 0
    if any(k in key_lower for k in ("nwm", "nowm", "no_watermark", "nomark")):
        score += 80
    if "video" in key_lower and "cover" not in key_lower:
        score += 40
    if any(k in key_lower for k in ("play", "stream", "download")):
        score += 30
    if "url" in key_lower:
        score += 10
    if any(k in key_lower for k in NON_VIDEO_KEY_FRAGMENTS):
        score -= 60
    if "wm" in key_lower and "nwm" not in key_lower:
        score -= 20
    return score


def _url_priority(url: str, key: str = "") -> int:
    score = _key_priority(key)
    lower = url.lower()
    if "playwm" in lower or "watermark" in lower:
        score -= 40
    if "/play/" in lower and "wm" not in lower:
        score += 25
    if ".mp4" in lower:
        score += 20
    if "/stream/" in lower:
        score += 30
    if ".m3u8" in lower:
        score += 15
    if IMAGE_EXT_PATTERN.search(lower):
        score -= 100
    if "stodownload" in lower and "picformat" not in lower:
        score += 35
    if _is_likely_cover_or_avatar_url(url):
        score -= 80
    return score


def _collect_from_value(
    value: Any,
    key: str,
    candidates: List[Tuple[int, str]],
) -> None:
    if isinstance(value, str):
        if _looks_like_video_url(value):
            candidates.append((_url_priority(value, key), _normalize_url(value)))
        return

    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and _looks_like_video_url(item):
                candidates.append((_url_priority(item, key), _normalize_url(item)))
            elif isinstance(item, dict):
                # play_addr: { url_list: [...] }
                for sub_key, sub_val in item.items():
                    _collect_from_value(sub_val, sub_key, candidates)
            else:
                _collect_from_value(item, key, candidates)
        return

    if isinstance(value, dict):
        # 优先按已知 key 名提取
        for name in VIDEO_KEY_NAMES:
            if name in value:
                _collect_from_value(value[name], name, candidates)
        for sub_key, sub_val in value.items():
            if sub_key not in VIDEO_KEY_NAMES:
                _collect_from_value(sub_val, sub_key, candidates)


def _walk(obj: Any, key: str, candidates: List[Tuple[int, str]], depth: int = 0) -> None:
    if depth > 12:
        return

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and _looks_like_video_url(v):
                candidates.append((_url_priority(v, k), _normalize_url(v)))
            else:
                _walk(v, k, candidates, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, key, candidates, depth + 1)
    elif isinstance(obj, str) and _looks_like_video_url(obj):
        candidates.append((_url_priority(obj, key), _normalize_url(obj)))


def _unwrap_data(obj: Any) -> Any:
    if isinstance(obj, dict) and "data" in obj:
        inner = obj["data"]
        if isinstance(inner, (dict, list)):
            return inner
    return obj


def _try_weixin_finder_format(response_json: Any) -> Optional[str]:
    """
    视频号解析 API 常见结构：
    {"code":200, "data":{"type":"video", "url":"...", "video_backup":[...]}}
    """
    inner = _unwrap_data(response_json)
    if not isinstance(inner, dict):
        return None
    if inner.get("type") != "video":
        return None

    main_url = inner.get("url")
    if isinstance(main_url, str) and _looks_like_video_url(main_url):
        return _normalize_url(main_url)

    backups = inner.get("video_backup")
    if isinstance(backups, list):
        best_url = None
        best_score = -1
        for item in backups:
            if not isinstance(item, dict):
                continue
            u = item.get("url")
            if not isinstance(u, str) or not _is_http_url(u):
                continue
            if _is_likely_cover_or_avatar_url(u):
                continue
            score = int(item.get("quality_type") or 0)
            if str(item.get("format", "")).lower() == "mp4":
                score += 20
            if "原画" in str(item.get("quality", "")):
                score += 10
            if score > best_score:
                best_score = score
                best_url = u
        if best_url:
            return _normalize_url(best_url)

    return None


def find_video_url(response_json: Any) -> Optional[str]:
    """
    从 API 响应 JSON 中递归搜索视频直链。

    策略：
    1. 优先匹配常见字段名（nwm_video_url、play_url、url_list 等）
    2. 递归遍历所有层级
    3. 识别 .mp4 / .m3u8 等视频 URL
    4. 优先无水印链接，排除封面/头像等

    Args:
        response_json: dict / list 或已解析的 JSON 对象

    Returns:
        最佳视频 URL，未找到返回 None
    """
    if response_json is None:
        return None

    # 视频号 / finder API 快速路径
    direct = _try_weixin_finder_format(response_json)
    if direct:
        return direct

    candidates: List[Tuple[int, str]] = []

    # 解包常见外层结构
    roots = [response_json]
    if isinstance(response_json, dict):
        for wrap_key in ("data", "result", "body", "item", "item_list", "aweme_detail"):
            inner = response_json.get(wrap_key)
            if inner is not None:
                roots.append(inner)

    for root in roots:
        if isinstance(root, list) and root and isinstance(root[0], dict):
            _collect_from_value(root[0], "item", candidates)
            _walk(root[0], "item", candidates)
        else:
            _collect_from_value(root, "", candidates)
            _walk(root, "", candidates)

    if not candidates:
        return None

    # 去重，按评分取最高
    seen = set()
    unique: List[Tuple[int, str]] = []
    for score, url in sorted(candidates, key=lambda x: -x[0]):
        if url not in seen:
            seen.add(url)
            unique.append((score, url))

    best_score, best_url = unique[0]
    if best_score < 0:
        # 全是封面类链接时的兜底：仍返回最高分
        pass

    return best_url


def find_cover_url(response_json: Any) -> Optional[str]:
    """从 JSON 中查找封面图 URL（辅助）."""
    if not isinstance(response_json, dict):
        return None

    cover_keys = ("cover", "cover_url", "coverUrl", "pic", "thumbnail", "origin_cover")
    candidates: List[str] = []

    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in cover_keys or "cover" in k.lower():
                    if isinstance(v, str) and _is_http_url(v):
                        candidates.append(v)
                    elif isinstance(v, dict) and "url" in v:
                        u = v.get("url")
                        if isinstance(u, str) and _is_http_url(u):
                            candidates.append(u)
                walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)

    walk(response_json)
    return candidates[0] if candidates else None
