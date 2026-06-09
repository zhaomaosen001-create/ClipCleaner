"""平台分享链接解析（内置 + 真实 API）."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union
from urllib.parse import urlparse

import requests

from clipcleaner.core.models import MediaInfo, media_info_from_video
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# 已知短视频平台域名关键词
PLATFORM_PATTERNS = {
    "douyin": [r"douyin\.com", r"iesdouyin\.com", r"v\.douyin\.com"],
    "xiaohongshu": [r"xiaohongshu\.com", r"xhslink\.com"],
    "weixin": [
        r"weixin\.qq\.com",
        r"channels\.weixin\.qq\.com",
        r"video\.weixin\.qq\.com",
        r"wxaurl\.cn",
        r"wx\.qq\.com",
    ],
    "kuaishou": [r"kuaishou\.com", r"gifshow\.com", r"v\.kuaishou\.com"],
    "bilibili": [r"bilibili\.com", r"b23\.tv"],
    "admuse": [r"admuse\.qq\.com"],
}


class InputType(Enum):
    PLATFORM = "platform"
    DIRECT = "direct"


@dataclass
class VideoInfo:
    title: str
    author: str
    cover_url: str
    video_url: str
    platform: str
    duration: float = 0.0
    referer: str = ""

    @property
    def source_label(self) -> str:
        labels = {
            "douyin": "抖音",
            "xiaohongshu": "小红书",
            "weixin": "视频号",
            "kuaishou": "快手",
            "bilibili": "B站",
            "admuse": "腾讯妙思",
            "direct": "直链",
            "unknown": "未知平台",
        }
        return labels.get(self.platform, self.platform)


def detect_platform(url: str) -> Optional[str]:
    """检测 URL 所属平台."""
    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return platform
    return None


def classify_input(url: str, original_text: str = "") -> InputType:
    """判断输入是平台分享链接还是普通视频直链."""
    from clipcleaner.url_extractor import (
        is_likely_direct_video,
        is_spa_page_url,
        is_weixin_share,
    )

    url = url.strip()
    if not url:
        raise ValueError("链接不能为空")

    parsed = urlparse(url)
    if not parsed.scheme:
        if re.search(r"^[\w.-]+\.[a-z]{2,}", url, re.I):
            url = "https://" + url.lstrip("/")
            parsed = urlparse(url)
        else:
            raise ValueError("无法识别链接格式，请粘贴完整分享 URL")

    if is_spa_page_url(url) or is_spa_page_url(original_text):
        return InputType.PLATFORM

    if detect_platform(url) or detect_platform(original_text):
        return InputType.PLATFORM

    if is_weixin_share(url, original_text):
        return InputType.PLATFORM

    if is_likely_direct_video(url):
        return InputType.DIRECT

    # 无法确认是 CDN 直链的，走平台/API 解析，避免把 HTML 页面当视频下载
    return InputType.PLATFORM


def _create_session(timeout: int = 30) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
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
    session.request_timeout = timeout  # type: ignore[attr-defined]
    return session


def resolve_platform_url(
    url: str,
    api_key: str = "",
    api_provider: str = "auto",
    api_base_url: str = "",
    original_text: str = "",
) -> MediaInfo:
    """
    解析平台分享链接，按优先级尝试：
    1. auto: 内置解析 → douyin.wtf API → 自定义 API
    2. builtin: 仅内置
    3. douyin_wtf: douyin.wtf 混合 API
    4. custom: 用户自定义 API
    """
    from clipcleaner.url_extractor import is_weixin_share

    platform = detect_platform(url) or detect_platform(original_text) or "unknown"
    if platform == "unknown" and is_weixin_share(url, original_text):
        platform = "weixin"
    logger.info("解析平台链接: %s (平台: %s, 提供方: %s)", url, platform, api_provider)

    # 腾讯妙思：优先浏览器自动化，失败再回退自定义 API
    if platform == "admuse":
        errors = []
        try:
            return _resolve_builtin(url, platform)
        except Exception as exc:
            errors.append(f"浏览器抓取: {exc}")
            logger.info("妙思浏览器抓取失败: %s", exc)
        if api_base_url or api_key or api_provider == "custom":
            try:
                return _resolve_custom(
                    url, api_key, api_base_url, platform, original_text
                )
            except Exception as exc:
                errors.append(f"自定义API: {exc}")
        import sys

        raise RuntimeError(
            "腾讯妙思解析失败：\n" + "\n".join(errors)
            + f"\n\n请在终端执行: bash scripts/install_playwright.sh"
            + f"\n或: {sys.executable} -m playwright install chromium"
        )

    if api_provider == "builtin":
        return _resolve_builtin(url, platform)

    if api_provider == "douyin_wtf":
        return _resolve_douyin_wtf(url, api_key)

    if api_provider == "custom":
        return _resolve_custom(url, api_key, api_base_url, platform, original_text)

    # auto 模式：逐级回退
    errors = []

    try:
        return _resolve_builtin(url, platform)
    except Exception as exc:
        errors.append(f"内置: {exc}")
        logger.info("内置解析失败，尝试 API: %s", exc)

    try:
        return _resolve_douyin_wtf(url, api_key)
    except Exception as exc:
        errors.append(f"douyin.wtf: {exc}")
        logger.info("douyin.wtf 失败: %s", exc)

    if _should_try_custom_api(platform, url, original_text, api_base_url, api_key):
        try:
            return _resolve_custom(url, api_key, api_base_url, platform, original_text)
        except Exception as exc:
            errors.append(f"自定义API: {exc}")
    elif api_base_url or api_key:
        errors.append(
            "自定义API: 当前链接不是已支持平台，"
            "微信/视频号类解析 API 无法解析第三方点播站点。"
        )

    hint = _unsupported_platform_hint(url, platform)
    raise RuntimeError(
        "所有解析方式均失败：\n" + "\n".join(errors)
        + (f"\n\n{hint}" if hint else "")
        + "\n\n建议：检查网络、在设置中切换 API 提供方，或直接粘贴视频直链（.mp4/.m3u8）。"
    )


def _should_try_custom_api(
    platform: str,
    url: str,
    original_text: str,
    api_base_url: str,
    api_key: str,
) -> bool:
    """未知平台的第三方站点不应走微信类自定义 API."""
    if not (api_base_url or api_key):
        return False
    from clipcleaner.url_extractor import is_weixin_share

    if platform != "unknown" or is_weixin_share(url, original_text):
        return True
    base = api_base_url.lower()
    if any(k in base for k in ("weixin", "wx", "finder", "channels")):
        return False
    return True


def _unsupported_platform_hint(url: str, platform: str) -> str:
    from clipcleaner.url_extractor import is_third_party_vod_page

    if platform != "unknown":
        return ""
    if is_third_party_vod_page(url):
        return (
            "该链接来自第三方点播网站（非抖音/小红书/视频号等），"
            "ClipCleaner 暂不支持从此类页面自动解析。"
            "请在浏览器开发者工具的网络面板中找到 .mp4 或 .m3u8 直链后粘贴下载。"
        )
    return (
        "该链接不属于已支持的短视频平台。"
        "如为视频直链请确认 URL 以 .mp4 或 .m3u8 结尾。"
    )


def _resolve_builtin(url: str, platform: str) -> MediaInfo:
    from clipcleaner.platform_parsers import BUILTIN_PARSERS, parse_with_builtin

    if platform not in BUILTIN_PARSERS:
        raise RuntimeError(f"平台 {platform} 暂无内置解析器")
    if platform == "xiaohongshu":
        from clipcleaner.platform_parsers import parse_xiaohongshu_media

        return parse_xiaohongshu_media(url)
    info = parse_with_builtin(platform, url)
    return media_info_from_video(info)


def _resolve_douyin_wtf(url: str, api_key: str) -> MediaInfo:
    from clipcleaner.api_providers import parse_douyin_wtf

    return media_info_from_video(parse_douyin_wtf(url, api_key))


def _resolve_custom(
    url: str,
    api_key: str,
    api_base_url: str,
    platform: str,
    original_text: str = "",
) -> MediaInfo:
    from clipcleaner.api_providers import parse_custom_api

    if not api_base_url:
        raise RuntimeError("自定义 API 模式需要配置 API 地址")
    return media_info_from_video(
        parse_custom_api(url, api_base_url, api_key, platform, original_text)
    )


def process_input(
    url: str,
    api_key: str = "",
    api_provider: str = "auto",
    api_base_url: str = "",
) -> tuple[InputType, Union[MediaInfo, str]]:
    """
    智能识别输入类型并返回处理结果。

    Returns:
        (InputType, VideoInfo | direct_url)
    """
    from clipcleaner.url_extractor import normalize_input

    share_url, original_text = normalize_input(url)
    input_type = classify_input(share_url, original_text)

    if input_type == InputType.PLATFORM:
        info = resolve_platform_url(
            share_url, api_key, api_provider, api_base_url, original_text
        )
        return input_type, info

    return input_type, share_url
