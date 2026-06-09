"""统一媒体信息模型."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from clipcleaner.api_resolver import VideoInfo


class ContentType(Enum):
    VIDEO = "video"
    IMAGE_NOTE = "image_note"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            ContentType.VIDEO: "视频",
            ContentType.IMAGE_NOTE: "图文",
            ContentType.UNKNOWN: "未知",
        }.get(self, "未知")


@dataclass
class MediaInfo:
    content_type: ContentType
    title: str
    author: str
    platform: str
    video_url: str = ""
    referer: str = ""
    image_urls: List[str] = field(default_factory=list)
    description: str = ""
    note_id: str = ""
    cover_url: str = ""
    source_url: str = ""
    duration: float = 0.0

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

    @property
    def type_label(self) -> str:
        return self.content_type.label


def media_info_from_video(info: VideoInfo) -> MediaInfo:
    """将旧版 VideoInfo 转为 MediaInfo."""
    return MediaInfo(
        content_type=ContentType.VIDEO,
        title=info.title,
        author=info.author,
        platform=info.platform,
        video_url=info.video_url,
        referer=info.referer,
        cover_url=info.cover_url,
        duration=info.duration,
        source_url=info.referer,
    )
