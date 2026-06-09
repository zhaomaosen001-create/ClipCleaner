"""批量下载任务队列."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from clipcleaner.core.models import ContentType, MediaInfo


class TaskState(Enum):
    WAITING = "等待中"
    RESOLVING = "解析中"
    DOWNLOADING = "下载中"
    COMPLETED = "已完成"
    FAILED = "失败"
    CANCELLED = "已取消"


@dataclass
class QueueTask:
    task_id: str
    raw_input: str
    state: TaskState = TaskState.WAITING
    media: Optional[MediaInfo] = None
    error: str = ""
    output_path: str = ""
    display_name: str = ""
    content_type: ContentType = ContentType.UNKNOWN


def split_batch_input(text: str) -> List[str]:
    """将多行输入拆分为独立任务（去空行、去重保序）."""
    lines: List[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        item = line.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        lines.append(item)
    return lines


class BatchQueue:
    """内存任务队列，供 GUI 调度解析与下载."""

    def __init__(self) -> None:
        self._tasks: Dict[str, QueueTask] = {}

    def add(self, task_id: str, raw_input: str) -> QueueTask:
        task = QueueTask(task_id=task_id, raw_input=raw_input)
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Optional[QueueTask]:
        return self._tasks.get(task_id)

    def remove(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def all_tasks(self) -> List[QueueTask]:
        return list(self._tasks.values())

    def waiting_tasks(self) -> List[QueueTask]:
        return [t for t in self._tasks.values() if t.state == TaskState.WAITING]

    def failed_tasks(self) -> List[QueueTask]:
        return [t for t in self._tasks.values() if t.state == TaskState.FAILED]

    def active_download_count(self) -> int:
        return sum(
            1 for t in self._tasks.values() if t.state == TaskState.DOWNLOADING
        )

    def reset_for_retry(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        task.state = TaskState.WAITING
        task.error = ""
        task.media = None
        task.output_path = ""
