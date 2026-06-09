"""内置平台链接解析（无需 API Key）."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import requests

from clipcleaner.api_resolver import VideoInfo, _create_session
from clipcleaner.core.models import ContentType, MediaInfo

logger = logging.getLogger(__name__)

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _expand_url(url: str, session: requests.Session) -> str:
    try:
        resp = session.get(url, allow_redirects=True, timeout=15)
        return resp.url
    except requests.RequestException:
        return url


def _extract_xhs_note_id(url: str) -> Optional[str]:
    for pat in (
        r"/explore/([a-f0-9]+)",
        r"/discovery/item/([a-f0-9]+)",
        r"noteId=([a-f0-9]+)",
    ):
        m = re.search(pat, url, re.I)
        if m:
            return m.group(1)
    return None


def _merge_xhs_share_params(original: str, target: str) -> str:
    """把分享链接里的 xsec_token 等参数合并到目标 URL."""
    orig_q = parse_qs(urlparse(original).query)
    parts = urlparse(target)
    merged = parse_qs(parts.query)
    for key in ("xsec_token", "xsec_source", "xhsshare", "source", "share_id"):
        if key in orig_q and key not in merged:
            merged[key] = orig_q[key]
    if not merged:
        return target
    query = urlencode({k: v[0] for k, v in merged.items()})
    return urlunparse(parts._replace(query=query))


def _xhs_fetch_urls(original: str, expanded: str) -> list[str]:
    """生成待尝试的小红书页面 URL（保留鉴权参数）."""
    candidates = [original.strip(), _merge_xhs_share_params(original, expanded)]
    if expanded not in candidates:
        candidates.append(expanded)
    seen: set[str] = set()
    result: list[str] = []
    for u in candidates:
        if u and u not in seen:
            seen.add(u)
            result.append(u)
    return result


def _extract_xhs_initial_state(html: str) -> Optional[dict]:
    """从 HTML 提取 window.__INITIAL_STATE__（比正则更稳）."""
    marker = "window.__INITIAL_STATE__="
    idx = html.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker)
    while start < len(html) and html[start].isspace():
        start += 1
    if start >= len(html) or html[start] != "{":
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = html[start : i + 1]
                try:
                    return json.loads(raw.replace("undefined", "null"))
                except json.JSONDecodeError as exc:
                    logger.debug("小红书 INITIAL_STATE JSON 解析失败: %s", exc)
                    return None
    return None


def _strip_watermark(url: str) -> str:
    return url.replace("playwm", "play").replace("/playwm/", "/play/")


def parse_douyin(url: str, session: requests.Session) -> VideoInfo:
    """抖音分享链接 → 无水印直链."""
    expanded = _expand_url(url, session)

    vid = None
    patterns = [
        r"/video/(\d+)",
        r"modal_id=(\d+)",
        r"item_ids=(\d+)",
        r"/note/(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, expanded)
        if m:
            vid = m.group(1)
            break

    if not vid:
        raise RuntimeError("无法从抖音链接提取视频 ID")

    # 方式 1: iesdouyin 移动端 SSR
    try:
        return _parse_douyin_ssr(vid, session)
    except Exception as exc:
        logger.debug("抖音 SSR 解析失败: %s", exc)

    # 方式 2: 旧版 iteminfo API
    api = f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={vid}"
    resp = session.get(api, headers={"User-Agent": DESKTOP_UA}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("item_list") or []
    if not items:
        raise RuntimeError("抖音 API 未返回视频数据")

    item = items[0]
    video = item.get("video", {})
    play_list = video.get("play_addr", {}).get("url_list") or []
    if not play_list:
        raise RuntimeError("抖音视频播放地址为空")

    video_url = _strip_watermark(play_list[0])
    return VideoInfo(
        title=item.get("desc") or f"douyin_{vid}",
        author=(item.get("author") or {}).get("nickname", "未知作者"),
        cover_url=(video.get("cover") or {}).get("url_list", [""])[0],
        video_url=video_url,
        platform="douyin",
        duration=float(video.get("duration", 0)) / 1000,
    )


def _parse_douyin_ssr(vid: str, session: requests.Session) -> VideoInfo:
    page_url = f"https://www.iesdouyin.com/share/video/{vid}"
    resp = session.get(
        page_url,
        headers={"User-Agent": MOBILE_UA},
        timeout=15,
    )
    resp.raise_for_status()
    html = resp.text

    m = re.search(
        r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>",
        html,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError("抖音页面未找到 _ROUTER_DATA")

    router = json.loads(m.group(1))
    loader = router.get("loaderData", {})
    page_data = None
    for key, val in loader.items():
        if "videoInfoRes" in str(key) or isinstance(val, dict) and "videoInfoRes" in val:
            page_data = val
            break
    if page_data is None:
        for val in loader.values():
            if isinstance(val, dict) and "videoInfoRes" in val:
                page_data = val
                break

    if not page_data:
        raise RuntimeError("抖音页面数据结构异常")

    items = page_data["videoInfoRes"]["item_list"]
    if not items:
        raise RuntimeError("抖音视频不可用")

    item = items[0]
    video = item["video"]
    play_list = video.get("play_addr", {}).get("url_list") or []
    if not play_list:
        raise RuntimeError("抖音播放列表为空")

    return VideoInfo(
        title=item.get("desc") or f"douyin_{vid}",
        author=item.get("author", {}).get("nickname", "未知作者"),
        cover_url=(video.get("cover") or {}).get("url_list", [""])[0],
        video_url=_strip_watermark(play_list[0]),
        platform="douyin",
        duration=float(video.get("duration", 0)) / 1000,
    )


def parse_bilibili(url: str, session: requests.Session) -> VideoInfo:
    """B站链接解析."""
    expanded = _expand_url(url, session)
    bvid = None
    aid = None

    m = re.search(r"/video/(BV[\w]+)", expanded, re.I)
    if m:
        bvid = m.group(1)
    m = re.search(r"av(\d+)", expanded, re.I)
    if m:
        aid = m.group(1)

    if not bvid and not aid:
        raise RuntimeError("无法从 B 站链接提取视频 ID")

    api = "https://api.bilibili.com/x/web-interface/view"
    params = {"bvid": bvid} if bvid else {"aid": aid}
    resp = session.get(api, params=params, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(body.get("message", "B站 API 错误"))

    data = body["data"]
    cid = data["cid"]
    bvid = data.get("bvid") or bvid

    play_api = "https://api.bilibili.com/x/player/playurl"
    play_resp = session.get(
        play_api,
        params={
            "bvid": bvid,
            "cid": cid,
            "qn": 80,
            "fnval": 0,
        },
        headers={"Referer": expanded, "User-Agent": DESKTOP_UA},
        timeout=15,
    )
    play_resp.raise_for_status()
    play_body = play_resp.json()
    if play_body.get("code") != 0:
        raise RuntimeError(play_body.get("message", "B站播放地址获取失败"))

    durl = play_body["data"]["durl"]
    if not durl:
        raise RuntimeError("B站 durl 为空")

    return VideoInfo(
        title=data.get("title", "bilibili_video"),
        author=data.get("owner", {}).get("name", "未知UP主"),
        cover_url=data.get("pic", ""),
        video_url=durl[0]["url"],
        platform="bilibili",
        duration=float(data.get("duration", 0)),
        referer=expanded,
    )


def parse_kuaishou(url: str, session: requests.Session) -> VideoInfo:
    """快手分享链接解析."""
    expanded = _expand_url(url, session)
    resp = session.get(
        expanded,
        headers={"User-Agent": MOBILE_UA},
        timeout=15,
    )
    resp.raise_for_status()
    html = resp.text

    # 尝试从页面 JSON 提取
    for pattern in (
        r"<script>window\.pageData\s*=\s*(\{.*?\})</script>",
        r"videoManifest.*?(\{.*?\})",
    ):
        m = re.search(pattern, html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                return _extract_kuaishou_from_json(data)
            except (json.JSONDecodeError, KeyError, RuntimeError):
                continue

    photo_id = None
    m = re.search(r"photoId[=:\"'](\w+)", html)
    if m:
        photo_id = m.group(1)

    if photo_id:
        api = f"https://v.m.chenzhongtech.com/rest/wd/photo/info?photoId={photo_id}"
        api_resp = session.get(api, headers={"User-Agent": MOBILE_UA}, timeout=15)
        if api_resp.ok:
            return _extract_kuaishou_from_json(api_resp.json())

    raise RuntimeError("快手链接解析失败，请尝试配置第三方 API")


def _extract_kuaishou_from_json(data: dict) -> VideoInfo:
    # 递归查找 mainUrl / photoUrl
    def find_video(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("mainUrl", "photoUrl", "srcNoMark") and isinstance(v, str) and v.startswith("http"):
                    return v
                found = find_video(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = find_video(item)
                if found:
                    return found
        return None

    video_url = find_video(data)
    if not video_url:
        raise RuntimeError("快手视频地址未找到")

    title = "kuaishou_video"
    author = "未知作者"
    if isinstance(data, dict):
        title = (
            data.get("caption")
            or data.get("photo", {}).get("caption")
            or title
        )
        author = (
            data.get("userName")
            or data.get("photo", {}).get("userName")
            or author
        )

    return VideoInfo(
        title=title,
        author=author,
        cover_url="",
        video_url=video_url,
        platform="kuaishou",
    )


def parse_xiaohongshu(url: str, session: requests.Session) -> VideoInfo:
    """小红书视频笔记解析（仅视频，图文请用 parse_xiaohongshu_media）."""
    media = parse_xiaohongshu_media(url, session)
    if media.content_type != ContentType.VIDEO:
        raise RuntimeError("该小红书链接为图文笔记，请使用图文下载功能")
    return VideoInfo(
        title=media.title,
        author=media.author,
        cover_url=media.cover_url,
        video_url=media.video_url,
        platform=media.platform,
        referer=media.referer,
        duration=media.duration,
    )


def parse_xiaohongshu_media(url: str, session: Optional[requests.Session] = None) -> MediaInfo:
    """小红书笔记解析（视频或图文）."""
    from clipcleaner.url_extractor import normalize_input

    share_url, _ = normalize_input(url)
    own_session = session is None
    if own_session:
        session = _create_session()
    expanded = _expand_url(share_url, session)
    note_id = _extract_xhs_note_id(share_url) or _extract_xhs_note_id(expanded)
    fetch_urls = _xhs_fetch_urls(share_url, expanded)

    last_error: Optional[str] = None
    best_video: Optional[MediaInfo] = None
    for fetch_url in fetch_urls:
        # 桌面 UA 返回 258 无水印流；移动 UA 返回 259 带片尾水印流
        for ua in (DESKTOP_UA, MOBILE_UA):
            try:
                resp = session.get(
                    fetch_url,
                    headers={
                        "User-Agent": ua,
                        "Referer": "https://www.xiaohongshu.com/",
                    },
                    timeout=20,
                )
                resp.raise_for_status()
                info = _parse_xhs_html(resp.text, note_id, fetch_url)
                if not info:
                    continue
                if info.content_type != ContentType.VIDEO:
                    return info
                if best_video is None or _xhs_video_url_rank(
                    info.video_url
                ) < _xhs_video_url_rank(best_video.video_url):
                    best_video = info
            except (json.JSONDecodeError, KeyError, RuntimeError) as exc:
                last_error = str(exc)
                logger.debug(
                    "小红书页面解析失败 (%s, %s): %s",
                    fetch_url[:60],
                    ua[:20],
                    exc,
                )

    if best_video:
        return best_video

    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"小红书链接解析失败，请尝试配置第三方 API{detail}")


def _parse_xhs_html(html: str, note_id: Optional[str], page_url: str) -> Optional[MediaInfo]:
    """从笔记页 HTML 的 __INITIAL_STATE__ 提取视频或图文信息."""
    state = _extract_xhs_initial_state(html)
    if not state:
        return None

    note = _extract_xhs_note_from_state(state, note_id)
    if not note:
        return None

    user = note.get("user", {}) or note.get("userInfo", {})
    cover = note.get("cover", {})
    cover_url = cover.get("url", "") if isinstance(cover, dict) else ""
    desc = note.get("desc") or ""
    title = note.get("title") or (desc[:40] if desc else "xiaohongshu_note")
    author = (
        user.get("nickName")
        or user.get("nickname")
        or user.get("name")
        or "未知作者"
    )
    nid = str(note.get("noteId") or note.get("id") or note_id or "")

    video_url = _find_xhs_video_url(note, html)
    if video_url:
        return MediaInfo(
            content_type=ContentType.VIDEO,
            title=title,
            author=author,
            platform="xiaohongshu",
            video_url=video_url,
            referer=page_url,
            cover_url=cover_url,
            description=desc,
            note_id=nid,
            source_url=page_url,
        )

    image_urls = _find_xhs_image_urls(note)
    if image_urls:
        return MediaInfo(
            content_type=ContentType.IMAGE_NOTE,
            title=title,
            author=author,
            platform="xiaohongshu",
            image_urls=image_urls,
            description=desc,
            note_id=nid,
            cover_url=cover_url or image_urls[0],
            source_url=page_url,
            referer=page_url,
        )
    return None


def _unwrap_xhs_note_entry(entry: dict) -> Optional[dict]:
    if not isinstance(entry, dict):
        return None
    note = entry.get("note")
    if isinstance(note, dict) and _xhs_note_has_content(note):
        return note
    if _xhs_note_has_content(entry):
        return entry
    return None


def _xhs_note_has_content(note: dict) -> bool:
    return bool(
        note.get("imageList")
        or note.get("imagesList")
        or note.get("video")
        or note.get("videoInfo")
    )


def _xhs_note_matches_id(note: dict, note_id: Optional[str]) -> bool:
    if not note_id:
        return True
    oid = str(note.get("noteId") or note.get("id") or "")
    return oid == note_id


def _extract_xhs_note_from_state(state: dict, note_id: Optional[str]) -> Optional[dict]:
    """优先从 noteDetailMap 读取笔记，避免递归误匹配."""
    note_block = state.get("note")
    if isinstance(note_block, dict):
        detail_map = note_block.get("noteDetailMap")
        if isinstance(detail_map, dict):
            if note_id and note_id in detail_map:
                note = _unwrap_xhs_note_entry(detail_map[note_id])
                if note:
                    return note
            for entry in detail_map.values():
                note = _unwrap_xhs_note_entry(entry)
                if note and _xhs_note_matches_id(note, note_id):
                    return note
    return _find_xhs_note(state, note_id)


def _find_xhs_note(state: dict, note_id: Optional[str]) -> Optional[dict]:
    def walk(obj):
        if isinstance(obj, dict):
            if _xhs_note_has_content(obj) and _xhs_note_matches_id(obj, note_id):
                return obj
            for v in obj.values():
                found = walk(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = walk(item)
                if found:
                    return found
        return None

    return walk(state)


_XHS_WM_STREAM_TYPES = frozenset({259})
_XHS_NOWM_STREAM_TYPES = frozenset({258})


def _xhs_is_watermark_stream_url(url: str) -> bool:
    """259 / MINI_APP 流为网页分享版，片尾含平台水印."""
    lower = url.lower()
    return (
        "/259/" in lower
        or "_259.mp4" in lower
        or "mini_app_259" in lower
    )


def _xhs_is_nowm_stream_url(url: str) -> bool:
    """258 流为网页端无片尾水印版本."""
    lower = url.lower()
    return "/258/" in lower or "_258.mp4" in lower


def _xhs_video_url_rank(url: str) -> int:
    """数值越小越优先（无水印优先）."""
    if not url:
        return 999
    if "sns-video-bd.xhscdn.com" in url and "/stream/" not in url.lower():
        return 0
    if _xhs_is_nowm_stream_url(url):
        return 1
    if _xhs_is_watermark_stream_url(url):
        return 100
    if _xhs_is_source_stream_url(url):
        return 50
    return 80


def _xhs_is_source_stream_url(url: str) -> bool:
    """小红书 xhscdn stream 直链."""
    lower = url.lower()
    if not lower.startswith("http"):
        return False
    if "watermark" in lower or "/wm/" in lower:
        return False
    return "xhscdn.com/stream/" in lower or "/stream/" in lower


def _xhs_origin_video_url(note: dict, html: str = "") -> Optional[str]:
    """从 consumer.originVideoKey 构造无水印原片地址."""
    video = note.get("video") or note.get("videoInfo") or {}
    consumer = video.get("consumer") or {}
    key = ""
    if isinstance(consumer, dict):
        key = str(
            consumer.get("originVideoKey") or consumer.get("origin_video_key") or ""
        ).strip()
    if not key and html:
        m = re.search(r'"originVideoKey"\s*:\s*"([^"]+)"', html)
        if m:
            key = m.group(1)
    if not key:
        return None
    key = _normalize_xhs_url(key).strip("/")
    if not key:
        return None
    return f"https://sns-video-bd.xhscdn.com/{key}"


def _xhs_stream_item_rank(item: dict) -> int:
    """stream 条目优先级，258 无水印最优先，259 带水印最后."""
    st = item.get("streamType")
    if st in _XHS_NOWM_STREAM_TYPES:
        return 0
    if st in _XHS_WM_STREAM_TYPES:
        return 100
    desc = str(item.get("streamDesc", "")).upper()
    if "259" in desc or "MINI_APP" in desc:
        return 100
    if "258" in desc or "X264_MP4" in desc:
        return 0
    return 50


def _xhs_pick_stream_item_url(item: dict) -> Optional[str]:
    """
    从单条 stream 记录选取无水印源视频地址。
    优先 sns-bak 备份直链（无 sign 过期），其次 masterUrl 源流。
    """
    if not isinstance(item, dict):
        return None

    backups = item.get("backupUrls") or item.get("backup_urls") or []
    for backup in backups:
        if isinstance(backup, str) and _xhs_is_source_stream_url(backup):
            return _normalize_xhs_url(backup)

    for key in ("masterUrl", "master_url"):
        url = item.get(key)
        if isinstance(url, str) and _xhs_is_source_stream_url(url):
            return _normalize_xhs_url(url)

    for backup in backups:
        if isinstance(backup, str) and backup.startswith("http"):
            return _normalize_xhs_url(backup)
    return None


def _pick_xhs_stream_url(streams: list) -> Optional[str]:
    """从 stream 列表选取无水印 mp4（优先 258，避开 259 片尾水印流）."""
    if not streams:
        return None

    items = [item for item in streams if isinstance(item, dict)]
    items.sort(key=_xhs_stream_item_rank)
    for item in items:
        url = _xhs_pick_stream_item_url(item)
        if url and not _xhs_is_watermark_stream_url(url):
            return url

    for item in items:
        url = _xhs_pick_stream_item_url(item)
        if url:
            return url
    return None


_XHS_WEBPIC_RE = re.compile(
    r"https?://sns-webpic[^/]*/\d+/[0-9a-f]+/([^!?\s\"']+)",
    re.IGNORECASE,
)


def _normalize_xhs_url(url: str) -> str:
    url = url.replace("\\u002F", "/").replace("\u002F", "/")
    if url.startswith("//"):
        url = "https:" + url
    return url


def _xhs_is_webpic_url(url: str) -> bool:
    return "sns-webpic" in url.lower() or "sns-img" in url.lower()


def _xhs_nowm_cdn_url(image_id: str, fmt: str = "jpg") -> str:
    image_id = image_id.strip().lstrip("/")
    if not image_id:
        return ""
    return f"https://ci.xiaohongshu.com/{image_id}?imageView2/2/format/{fmt}"


def _xhs_image_id_from_url(url: str) -> Optional[str]:
    """从 webpic / ci CDN 链接提取图片 ID."""
    if not url:
        return None
    url = _normalize_xhs_url(url.split("!")[0].split("?")[0])

    if "ci.xiaohongshu.com" in url:
        path = urlparse(url).path.lstrip("/")
        return path or None

    if _xhs_is_webpic_url(url):
        match = _XHS_WEBPIC_RE.search(url)
        if match:
            return match.group(1)
        seg = urlparse(url).path.rstrip("/").split("/")[-1]
        if seg and (seg.startswith("1040") or seg.startswith("spectrum/")):
            return seg
    return None


def _xhs_url_to_nowm(url: str) -> Optional[str]:
    """将任意小红书图片链接转为无水印 ci CDN 地址."""
    image_id = _xhs_image_id_from_url(url)
    if image_id:
        return _xhs_nowm_cdn_url(image_id)
    return None


def _xhs_collect_image_candidates(item: dict) -> list[tuple[int, str]]:
    """收集图片候选 URL，按优先级排序."""
    scene_rank = {
        "CRD_PRV_WEBP": 0,
        "CRD": 1,
        "H5_DTL": 2,
        "DTL": 2,
        "H5_PRV": 3,
        "SHR": 4,
        "WB_PRV": 8,
        "WB_DFT": 9,
    }
    candidates: list[tuple[int, str]] = []
    rank = 0
    for key in ("urlDefault", "url_default", "urlPre", "url", "originUrl", "picUrl"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            candidates.append((rank, _normalize_xhs_url(val)))
            rank += 1

    info_list = item.get("infoList") or item.get("info_list") or []
    if isinstance(info_list, list):
        for info in info_list:
            if not isinstance(info, dict):
                continue
            u = info.get("url")
            if not isinstance(u, str) or not u.strip():
                continue
            scene = str(info.get("imageScene") or "")
            candidates.append(
                (10 + scene_rank.get(scene, 5), _normalize_xhs_url(u))
            )
    candidates.sort(key=lambda x: x[0])
    return candidates


def _pick_xhs_image_url(item: dict) -> Optional[str]:
    """优先选取无水印原图地址."""
    if not isinstance(item, dict):
        return None

    trace_id = str(item.get("traceId") or item.get("trace_id") or "").strip()
    file_id = str(item.get("fileId") or item.get("file_id") or "").strip()

    if trace_id:
        return _xhs_nowm_cdn_url(trace_id)

    raw_url = item.get("url") or ""
    if isinstance(raw_url, str):
        raw_url = _normalize_xhs_url(raw_url)
        if trace_id and file_id and file_id in raw_url:
            return _xhs_nowm_cdn_url(trace_id)

    for _, src in _xhs_collect_image_candidates(item):
        nowm = _xhs_url_to_nowm(src)
        if nowm:
            return nowm

    return None


def _find_xhs_image_urls(note: dict) -> list[str]:
    """从笔记对象提取无水印图片 URL 列表."""
    image_list = (
        note.get("imageList")
        or note.get("imagesList")
        or note.get("image_list")
        or []
    )
    if not isinstance(image_list, list):
        return []

    urls: list[str] = []
    for item in image_list:
        if isinstance(item, str) and item.startswith("http"):
            picked = _xhs_url_to_nowm(item) or _normalize_xhs_url(item)
            urls.append(picked)
            continue
        picked = _pick_xhs_image_url(item)
        if picked:
            urls.append(picked)

    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def _find_xhs_video_url(note: dict, html: str = "") -> Optional[str]:
    """提取小红书视频笔记的无水印源视频直链."""
    origin = _xhs_origin_video_url(note, html)
    if origin:
        return origin

    video = note.get("video") or note.get("videoInfo") or {}
    if not isinstance(video, dict):
        return None

    media = video.get("media")
    if isinstance(media, dict):
        stream = media.get("stream")
        if isinstance(stream, dict):
            # 优先 h264；同编码内 258 优先于 259
            for codec in ("h264", "h265", "h266", "av1"):
                url = _pick_xhs_stream_url(stream.get(codec) or [])
                if url and not _xhs_is_watermark_stream_url(url):
                    return url
            for codec in ("h264", "h265", "h266", "av1"):
                url = _pick_xhs_stream_url(stream.get(codec) or [])
                if url:
                    return url

    media_v2 = video.get("mediaV2")
    if isinstance(media_v2, str) and media_v2.strip():
        try:
            parsed = json.loads(media_v2)
            stream = parsed.get("stream")
            if isinstance(stream, dict):
                for codec in ("h264", "h265", "h266", "av1"):
                    url = _pick_xhs_stream_url(stream.get(codec) or [])
                    if url and not _xhs_is_watermark_stream_url(url):
                        return url
                for codec in ("h264", "h265", "h266", "av1"):
                    url = _pick_xhs_stream_url(stream.get(codec) or [])
                    if url:
                        return url
        except json.JSONDecodeError:
            logger.debug("小红书 mediaV2 JSON 解析失败")

    fallback: list[str] = []
    for key in ("media", "consumer", "originVideoKey"):
        val = video.get(key)
        if isinstance(val, dict):
            for ukey in ("masterUrl", "master_url", "url", "videoUrl"):
                u = val.get(ukey)
                if isinstance(u, str) and _xhs_is_source_stream_url(u):
                    fallback.append(_normalize_xhs_url(u))
        elif isinstance(val, str) and _xhs_is_source_stream_url(val):
            fallback.append(_normalize_xhs_url(val))

    for candidate in video.get("urlList") or video.get("url_list") or []:
        if isinstance(candidate, str) and _xhs_is_source_stream_url(candidate):
            fallback.append(_normalize_xhs_url(candidate))

    fallback.sort(key=_xhs_video_url_rank)
    return fallback[0] if fallback else None


def parse_weixin(url: str, session: requests.Session) -> VideoInfo:
    """微信视频号链接解析."""
    expanded = _expand_url(url, session)
    resp = session.get(
        expanded,
        headers={"User-Agent": MOBILE_UA},
        timeout=15,
    )
    resp.raise_for_status()
    html = resp.text

    # 提取 objectId / nonceId
    for pattern in (
        r'"url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
        r"url\s*=\s*['\"](https?://[^'\"]+\.mp4[^'\"]*)['\"]",
    ):
        m = re.search(pattern, html)
        if m:
            video_url = unquote(m.group(1).replace("\\/", "/"))
            title_m = re.search(r'"title"\s*:\s*"([^"]+)"', html)
            author_m = re.search(r'"nickname"\s*:\s*"([^"]+)"', html)
            return VideoInfo(
                title=title_m.group(1) if title_m else "weixin_video",
                author=author_m.group(1) if author_m else "未知作者",
                cover_url="",
                video_url=video_url,
                platform="weixin",
            )

    raise RuntimeError("视频号链接解析失败，请尝试配置第三方 API")


def parse_admuse(url: str, session=None) -> VideoInfo:
    """腾讯妙思 — Playwright 浏览器自动化（session 参数兼容接口）."""
    from clipcleaner.admuse_scraper import parse_admuse_url

    return parse_admuse_url(url)


BUILTIN_PARSERS = {
    "douyin": parse_douyin,
    "bilibili": parse_bilibili,
    "kuaishou": parse_kuaishou,
    "xiaohongshu": parse_xiaohongshu,
    "weixin": parse_weixin,
    "admuse": parse_admuse,
}


def parse_with_builtin(platform: str, url: str) -> VideoInfo:
    """使用内置解析器."""
    parser = BUILTIN_PARSERS.get(platform)
    if not parser:
        raise RuntimeError(f"平台 {platform} 无内置解析器")
    if platform == "admuse":
        return parser(url)
    session = _create_session()
    return parser(url, session)
