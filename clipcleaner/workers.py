"""后台任务线程封装（供 GUI 使用）."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal


class WorkerSignals(QObject):
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class DownloadSignals(QObject):
    """下载线程 → 主线程 UI 更新（跨线程安全）."""

    progress = pyqtSignal(str, str)  # task_id, status_text
    finished = pyqtSignal(str, object)  # task_id, DownloadTask


class GenericWorker(QThread):
    """在后台线程执行任意可调用对象."""

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        cancel_fn = self.kwargs.get("cancel_target")
        if cancel_fn and hasattr(cancel_fn, "cancel"):
            cancel_fn.cancel()

    def run(self) -> None:
        try:
            call_kwargs = {
                k: v for k, v in self.kwargs.items() if k != "cancel_target"
            }
            params = inspect.signature(self.fn).parameters
            if "progress_callback" in params:
                call_kwargs["progress_callback"] = self._emit_progress
            result = self.fn(*self.args, **call_kwargs)
            if not self._cancelled:
                self.signals.finished.emit(result)
        except InterruptedError as exc:
            self.signals.error.emit(str(exc))
        except Exception as exc:
            self.signals.error.emit(str(exc))

    def _emit_progress(self, percent: float, message: str = "") -> None:
        self.signals.progress.emit(percent, message)
