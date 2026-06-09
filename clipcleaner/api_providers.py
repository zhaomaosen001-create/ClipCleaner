"""第三方解析 API 适配器."""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import requests

from clipcleaner.api_resolver import VideoInfo, _create_session
from clipcleaner.url_finder import find_cover_url, find_video_url

logger = logging.getLogger(__name__)

# 公开可用的混合解析 API（Douyin/TikTok/Bilibili 等）
DOUYIN_WTF_API = "https://api.douyin.wtf/api/hybrid/video_data"


def _dig(data: Any, *keys: str, default: Any = None) -> Any:
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _unwrap_response(body: dict) -> dict:
    """展开常见 API 包装层，保留原始 body 供递归搜索."""
    if not isinstance(body, dict):
        return body
    if "data" in body and isinstance(body["data"], (dict, list)):
        return body["data"]
    return body


def _is_api_success(body: dict) -> bool:
    """判断 API 业务层是否成功."""
    code = body.get("code")
    if code is not None and code not in (0, 200, "0", "200"):
        return False
    status = body.get("status")
    if status is not None and str(status).lower() not in ("success", "ok", "true"):
        return False
    return True


def _detect_platform(data: dict, video_url: str, fallback: str = "unknown") -> str:
    """根据响应内容与 URL 推断平台."""
    url_lower = video_url.lower()
    if "finder.video.qq.com" in url_lower or "channels.weixin" in url_lower:
        return "weixin"
    if "douyin" in url_lower or "snssdk" in url_lower:
        return "douyin"
    if "bilivideo" in url_lower or "hdslb" in url_lower:
        return "bilibili"
    if "xhscdn" in url_lower or "xiaohongshu" in url_lower:
        return "xiaohongshu"
    if "kuaishou" in url_lower:
        return "kuaishou"

    raw_type = data.get("type") or data.get("platform")
    if isinstance(raw_type, str):
        t = raw_type.lower()
        if t in ("video", "image", "photo"):
            # type=video 是媒体类型，不是平台名
            pass
        elif t not in ("unknown", ""):
            return t.replace("tiktok", "douyin")

    return fallback


def _build_video_info(response_json: Any, platform: str = "unknown") -> VideoInfo:
    """从完整 API 响应构建 VideoInfo，视频 URL 递归搜索."""
    video_url = find_video_url(response_json)
    if not video_url:
        raise RuntimeError(
            "API 响应中未找到视频直链。"
            "已递归搜索 play_url、url_list、play_addr、.mp4/.m3u8 等字段均未命中。"
        )

    data: Any = response_json
    if isinstance(data, dict):
        data = _unwrap_response(data)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    if not isinstance(data, dict):
        data = {}

    title = (
        data.get("title")
        or data.get("desc")
        or _dig(data, "video_data", "title")
        or "未命名视频"
    )
    author = (
        _dig(data, "author", "name")
        or _dig(data, "author", "nickname")
        or _dig(data, "author", "unique_id")
        or data.get("nickname")
        or data.get("author")
        or "未知作者"
    )
    if isinstance(author, dict):
        author = author.get("name") or author.get("nickname") or "未知作者"

    plat = _detect_platform(data, video_url, platform)

    cover = (
        find_cover_url(response_json)
        or data.get("cover")
        or data.get("cover_url")
        or ""
    )

    duration = float(
        data.get("duration")
        or _dig(data, "video_data", "duration")
        or 0
    )

    return VideoInfo(
        title=str(title),
        author=str(author),
        cover_url=str(cover) if cover else "",
        video_url=video_url,
        platform=str(plat),
        duration=duration,
    )


def parse_douyin_wtf(url: str, api_key: str = "") -> VideoInfo:
    """
    调用 douyin.wtf 混合解析 API。
    支持抖音 / TikTok / B站 等，无需 API Key。
    """
    session = _create_session()
    params = {"url": url, "minimal": "false"}
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = session.get(DOUYIN_WTF_API, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    body = resp.json()

    if body.get("code") not in (None, 0, 200) and body.get("status") != "success":
        msg = body.get("message") or body.get("msg") or str(body)
        raise RuntimeError(f"douyin.wtf 解析失败: {msg}")

    logger.debug("douyin.wtf 响应已收到，开始递归搜索视频 URL")
    return _build_video_info(body)


def _api_key_in_url(url: str, api_key: str) -> bool:
    """判断 URL 中是否已包含 API Key（参数或占位符已替换）."""
    if any(p in url for p in ("{apikey}", "{api_key}", "{key}", "{token}", "{appkey}")):
        return False
    lower = url.lower()
    if any(f"{name}=" in lower for name in ("apikey", "api_key", "key", "token", "appkey")):
        return True
    return bool(api_key and api_key in url)


def _apply_url_placeholders(
    template: str,
    share_url: str,
    api_key: str,
    original_text: str = "",
) -> str:
    """替换 URL 模板中的 {url}、{apikey}、{link}、{text} 等占位符."""
    result = template
    encoded_url = quote(share_url, safe="")
    result = result.replace("{url}", encoded_url)
    result = result.replace("{link}", encoded_url)
    result = result.replace("{share_url}", encoded_url)
    text = original_text or share_url
    result = result.replace("{text}", quote(text, safe=""))
    if api_key:
        encoded_key = quote(api_key, safe="")
        for placeholder in ("{apikey}", "{api_key}", "{key}", "{token}", "{appkey}"):
            result = result.replace(placeholder, encoded_key)
    return result


def _share_url_already_in_endpoint(endpoint: str, share_url: str) -> bool:
    if share_url in endpoint:
        return True
    encoded = quote(share_url, safe="")
    return encoded in endpoint


def _append_share_url_query(
    url: str,
    share_url: str,
    original_text: str = "",
    platform: str = "",
) -> str:
    """将分享链接追加为查询参数（url / link / text）."""
    if _share_url_already_in_endpoint(url, share_url):
        return url

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    # 国内 API 常见参数名，按需补齐
    if "url" not in query:
        query["url"] = share_url
    if "link" not in query:
        query["link"] = share_url

    if platform == "weixin" or "weixin" in share_url.lower():
        if "text" not in query and original_text:
            query["text"] = original_text
        if "share_url" not in query:
            query["share_url"] = share_url

    new_query = urlencode(query)
    return urlunparse(parsed._replace(query=new_query))


def _append_api_key_query(url: str, api_key: str, param_name: str = "apikey") -> str:
    """将 API Key 追加为 URL 查询参数（国内 API 最常见方式）."""
    if not api_key or _api_key_in_url(url, api_key):
        return url

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for name in (param_name, "apikey", "api_key", "key", "token"):
        if name not in query:
            query[name] = api_key
            break

    new_query = urlencode(query)
    return urlunparse(parsed._replace(query=new_query))


def _build_custom_request(
    share_url: str,
    api_base_url: str,
    api_key: str,
    platform: str,
    original_text: str = "",
) -> Tuple[str, str, Dict[str, Any], Dict[str, str]]:
    """
    构建自定义 API 请求。
    Returns: (method, request_url, json_body_or_empty, headers)
    """
    headers: Dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key

    has_placeholders = any(
        p in api_base_url for p in ("{url}", "{link}", "{text}", "{share_url}")
    )
    # 国内解析 API 绝大多数为 GET；无占位符时也自动追加 url 参数
    use_get = has_placeholders or "?" in api_base_url or True

    endpoint = _apply_url_placeholders(api_base_url, share_url, api_key, original_text)
    endpoint = _append_api_key_query(endpoint, api_key)
    endpoint = _append_share_url_query(endpoint, share_url, original_text, platform)

    if use_get:
        return "GET", endpoint, {}, headers

    # POST 备用
    payload: Dict[str, Any] = {
        "url": share_url,
        "link": share_url,
        "platform": platform,
    }
    if original_text:
        payload["text"] = original_text
    if api_key and "apikey" not in payload:
        payload["apikey"] = api_key
    post_url = _append_api_key_query(api_base_url, api_key)
    headers["Content-Type"] = "application/json"
    return "POST", post_url, payload, headers


def parse_custom_api(
    url: str,
    api_base_url: str,
    api_key: str = "",
    platform: str = "unknown",
    original_text: str = "",
) -> VideoInfo:
    """
    自定义 REST API。
    支持 GET/POST，URL 模板占位符：{url} {apikey} {api_key} {key}
    未使用占位符时，自动将 apikey 追加为查询参数 / POST 字段。
    """
    if not api_base_url:
        raise RuntimeError("未配置自定义 API 地址")

    if not api_key and not _api_key_in_url(api_base_url, ""):
        raise RuntimeError(
            "请先在「设置」中填写 API Key。\n"
            "或在 API 地址中使用 {apikey} 占位符。"
        )

    from clipcleaner.url_extractor import is_weixin_share

    if is_weixin_share(url, original_text):
        platform = "weixin"

    session = _create_session()
    method, request_url, payload, headers = _build_custom_request(
        url, api_base_url, api_key, platform, original_text
    )
    logger.info("自定义 API: %s %s... url=%s", method, request_url[:80], url[:60])

    if method == "GET":
        resp = session.get(request_url, headers=headers, timeout=30)
    else:
        resp = session.post(request_url, json=payload, headers=headers, timeout=30)

    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict) and not _is_api_success(body):
        msg = body.get("msg") or body.get("message") or str(body)
        raise RuntimeError(f"自定义 API 解析失败: {msg}")

    logger.debug(
        "自定义 API 响应 keys: %s",
        list(body.keys()) if isinstance(body, dict) else type(body),
    )
    return _build_video_info(body, platform)


PROVIDERS = {
    "auto": None,  # 由 api_resolver 编排
    "builtin": None,
    "douyin_wtf": parse_douyin_wtf,
    "custom": parse_custom_api,
}
