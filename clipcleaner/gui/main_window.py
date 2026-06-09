"""ClipCleaner 主窗口."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QCloseEvent, QIcon, QPalette, QColor
from clipcleaner.gui.check_toggle import CheckToggle
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from clipcleaner.api_resolver import InputType, classify_input, process_input
from clipcleaner.config import ConfigManager, setup_logging
from clipcleaner.core.batch_queue import BatchQueue, TaskState, split_batch_input
from clipcleaner.core.models import ContentType, MediaInfo
from clipcleaner.download.image_note import download_image_note
from clipcleaner.downloader import DownloadStatus, DownloadTask, DownloadWorker
from clipcleaner.icon_utils import ensure_icons_exist, get_app_icon
from clipcleaner.paths import APP_NAME
from clipcleaner.url_extractor import normalize_input
from clipcleaner.utils import sanitize_filename
from clipcleaner.workers import DownloadSignals, GenericWorker

from .dialogs import SettingsDialog

logger = logging.getLogger(__name__)

COL_INDEX = 0
COL_CHECK = 1
COL_TYPE = 2
COL_FILENAME = 3
COL_SOURCE = 4
COL_AUTHOR = 5
COL_STATUS = 6
COL_ACTION = 7
COL_TIME = 8


@dataclass
class TaskRow:
    task_id: str
    table_index: int = -1
    filename: str = ""
    content_type: str = "未知"
    source: str = ""
    author: str = ""
    status: str = TaskState.WAITING.value
    output_path: str = ""
    started_at: Optional[float] = None
    duration_text: str = ""
    download_worker: Optional[DownloadWorker] = field(default=None, repr=False)
    image_cancel: Optional[threading.Event] = field(default=None, repr=False)


class MainWindow(QMainWindow):
    """ClipCleaner 主界面."""

    def __init__(self, config_manager: ConfigManager) -> None:
        super().__init__()
        self.config_manager = config_manager
        self._queue = BatchQueue()
        self._rows: Dict[str, TaskRow] = {}
        self._task_counter = 0
        self._resolve_workers: Dict[str, GenericWorker] = {}
        self._download_workers: Dict[str, DownloadWorker] = {}
        self._batch_running = False

        self._download_signals = DownloadSignals()
        self._download_signals.progress.connect(self._on_download_progress)
        self._download_signals.finished.connect(self._on_download_finished)

        ensure_icons_exist()
        app_icon = get_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self.setWindowTitle("ClipCleaner - 多平台下载")
        self.resize(1020, 680)
        self._center_window()
        self._load_styles()
        self._build_menu()
        self._build_ui()
        self._setup_tray()
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(500)
        self._duration_timer.timeout.connect(self._tick_durations)
        self._duration_timer.start()
        self._append_log("ClipCleaner 已启动")

    def _center_window(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def _load_styles(self) -> None:
        from clipcleaner.paths import get_resource_dir

        qss_path = get_resource_dir() / "clipcleaner" / "gui" / "styles.qss"
        if not qss_path.exists():
            qss_path = Path(__file__).parent / "styles.qss"
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                qss = f.read()
            self.setStyleSheet(qss)

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        act_import = QAction("从 txt 导入链接...", self)
        act_import.triggered.connect(self._import_txt)
        file_menu.addAction(act_import)
        act_open_dir = QAction("打开下载目录", self)
        act_open_dir.triggered.connect(self._open_download_dir)
        file_menu.addAction(act_open_dir)
        file_menu.addSeparator()
        act_exit = QAction("退出", self)
        act_exit.triggered.connect(self._quit_app)
        file_menu.addAction(act_exit)

        settings_menu = menubar.addMenu("设置")
        act_settings = QAction("偏好设置...", self)
        act_settings.triggered.connect(self._show_settings)
        settings_menu.addAction(act_settings)

        help_menu = menubar.addMenu("帮助")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        hint = QLabel(
            "支持抖音/小红书/快手/B站视频（含去水印）及小红书图文笔记（无水印图+文案），"
            "视频号需第三方API辅助。"
        )
        hint.setObjectName("urlHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.url_input = QTextEdit()
        self.url_input.setObjectName("urlInput")
        self.url_input.setPlaceholderText(
            "粘贴一条或多条分享链接 / 分享全文（每行一条）..."
        )
        palette = self.url_input.palette()
        palette.setColor(QPalette.Text, QColor("#2c3e50"))
        palette.setColor(QPalette.Base, QColor("#ffffff"))
        palette.setColor(QPalette.PlaceholderText, QColor("#555555"))
        self.url_input.setPalette(palette)
        self.url_input.setMaximumHeight(100)
        root.addWidget(self.url_input)

        input_row = QHBoxLayout()
        self.btn_paste = QPushButton("粘贴")
        self.btn_paste.clicked.connect(self._on_paste)
        self.btn_import = QPushButton("导入 txt")
        self.btn_import.clicked.connect(self._import_txt)
        self.btn_enqueue = QPushButton("加入队列")
        self.btn_enqueue.setObjectName("btnDownload")
        self.btn_enqueue.clicked.connect(self._on_enqueue)
        self.btn_start = QPushButton("开始下载")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.clicked.connect(self._on_start_batch)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.setObjectName("btnSettings")
        self.btn_settings.clicked.connect(self._show_settings)

        input_row.addWidget(self.btn_paste)
        input_row.addWidget(self.btn_import)
        input_row.addStretch()
        input_row.addWidget(self.btn_enqueue)
        input_row.addWidget(self.btn_start)
        input_row.addWidget(self.btn_settings)
        root.addLayout(input_row)

        self.table = QTableWidget(0, 9)
        self.table.setObjectName("fileTable")
        self.table.setHorizontalHeaderLabels(
            ["序号", "勾选", "类型", "文件名", "来源", "作者", "状态", "操作", "下载所需时间"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.table.horizontalHeader().setSectionResizeMode(COL_INDEX, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_INDEX, 44)
        self.table.horizontalHeader().setSectionResizeMode(COL_CHECK, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_CHECK, 52)
        self.table.horizontalHeader().setSectionResizeMode(COL_TYPE, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_TYPE, 52)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setMinimumSectionSize(48)
        for col in (COL_FILENAME, COL_SOURCE, COL_AUTHOR, COL_STATUS):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(COL_ACTION, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(COL_TIME, QHeaderView.Stretch)
        self.table.setColumnWidth(COL_FILENAME, 240)
        self.table.setColumnWidth(COL_SOURCE, 76)
        self.table.setColumnWidth(COL_AUTHOR, 88)
        self.table.setColumnWidth(COL_STATUS, 108)
        self.table.setColumnWidth(COL_ACTION, 120)
        self.table.setColumnWidth(COL_TIME, 100)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(280)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        root.addWidget(self.table, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.clicked.connect(lambda: self._set_all_checks(True))
        self.btn_select_none = QPushButton("取消全选")
        self.btn_select_none.clicked.connect(lambda: self._set_all_checks(False))
        self.btn_delete_selected = QPushButton("删除选中")
        self.btn_delete_selected.clicked.connect(self._delete_selected)
        self.btn_retry_failed = QPushButton("重试失败")
        self.btn_retry_failed.clicked.connect(self._retry_failed)
        self.btn_clear_done = QPushButton("清空已完成")
        self.btn_clear_done.clicked.connect(self._clear_completed)
        self.btn_open_dir = QPushButton("打开下载目录")
        self.btn_open_dir.clicked.connect(self._open_download_dir)

        btn_row.addWidget(self.btn_select_all)
        btn_row.addWidget(self.btn_select_none)
        btn_row.addWidget(self.btn_delete_selected)
        btn_row.addWidget(self.btn_retry_failed)
        btn_row.addWidget(self.btn_clear_done)
        btn_row.addWidget(self.btn_open_dir)
        btn_row.addStretch()
        root.addLayout(btn_row)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_label = QLabel("就绪")
        self.progress_label.setStyleSheet("color: #666; font-size: 12px;")
        progress_row.addWidget(self.progress_bar, stretch=1)
        progress_row.addWidget(self.progress_label)
        root.addLayout(progress_row)

        self.tabs = QTabWidget()
        self.log_view = QTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.tabs.addTab(self.log_view, "日志")
        root.addWidget(self.tabs)

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("ClipCleaner")
        icon = get_app_icon()
        if icon.isNull():
            icon = self.style().standardIcon(self.style().SP_ComputerIcon)
        self.tray.setIcon(icon)

        tray_menu = QMenu()
        act_show = tray_menu.addAction("显示主窗口")
        act_show.triggered.connect(self._show_from_tray)
        act_quit = tray_menu.addAction("退出")
        act_quit.triggered.connect(self._quit_app)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _append_log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f"[{ts}] {message}")
        logger.info(message)

    def _set_progress(self, percent: float, message: str = "") -> None:
        self.progress_bar.setValue(int(percent))
        self.progress_label.setText(message or f"{percent:.0f}%")

    def _on_paste(self) -> None:
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.url_input.setPlainText(text)
            self._append_log("已从剪贴板粘贴链接")

    def _import_txt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入链接文件", "", "文本文件 (*.txt);;所有文件 (*)"
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self.url_input.setPlainText(content.strip())
        lines = split_batch_input(content)
        self._append_log(f"已从文件导入 {len(lines)} 条链接")

    def _on_enqueue(self) -> None:
        text = self.url_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入至少一条分享链接。")
            return
        added = self._enqueue_lines(split_batch_input(text), clear_input=True)
        self._append_log(f"已加入队列 {added} 条任务")
        self._sync_start_button_state()

    def _enqueue_lines(self, lines: List[str], clear_input: bool = False) -> int:
        added = 0
        for line in lines:
            self._task_counter += 1
            task_id = f"task_{self._task_counter}"
            self._queue.add(task_id, line)
            row = TaskRow(
                task_id=task_id,
                filename=line[:48] + ("..." if len(line) > 48 else ""),
                status=TaskState.WAITING.value,
            )
            self._rows[task_id] = row
            self._add_table_row(row)
            added += 1
        if clear_input and added:
            self.url_input.clear()
        return added

    def _has_active_workers(self) -> bool:
        if self._download_workers:
            return True
        if self._queue.active_download_count() > 0:
            return True
        return any(w.isRunning() for w in self._resolve_workers.values())

    def _sync_start_button_state(self) -> None:
        """根据队列与后台任务状态更新「开始下载」按钮."""
        if self._has_active_workers():
            self.btn_start.setEnabled(False)
            return
        self._batch_running = False
        self.btn_start.setEnabled(True)

    def _on_start_batch(self) -> None:
        text = self.url_input.toPlainText().strip()
        if text:
            added = self._enqueue_lines(split_batch_input(text), clear_input=True)
            if added:
                self._append_log(f"已加入队列 {added} 条任务")

        waiting = self._queue.waiting_tasks()
        if not waiting:
            QMessageBox.information(self, "提示", "队列中没有等待中的任务。")
            return
        self._batch_running = True
        self.btn_start.setEnabled(False)
        self._append_log(f"开始批量处理，等待中 {len(waiting)} 条")
        self._pump_batch()

    def _pump_batch(self) -> None:
        if not self._batch_running:
            self._sync_start_button_state()
            return

        cfg = self.config_manager.config
        max_concurrent = cfg.max_concurrent_downloads
        active = sum(1 for w in self._resolve_workers.values() if w.isRunning())
        active += len(self._download_workers)

        for task in self._queue.waiting_tasks():
            if active >= max_concurrent:
                break
            self._start_resolve(task.task_id)
            active += 1

        if not self._queue.waiting_tasks() and not self._has_active_workers():
            self._batch_running = False
            self._sync_start_button_state()
            self._set_progress(100, "批量任务完成")
            self._append_log("批量下载已全部结束")
            QTimer.singleShot(3000, lambda: self._set_progress(0, "就绪"))

    def _start_resolve(self, task_id: str) -> None:
        task = self._queue.get(task_id)
        row = self._rows.get(task_id)
        if not task or not row:
            return

        task.state = TaskState.RESOLVING
        self._start_task_timer(task_id)
        self._update_row_status(task_id, TaskState.RESOLVING.value)
        cfg = self.config_manager.config
        raw = task.raw_input

        def resolve_task():
            try:
                share_url, _ = normalize_input(raw)
                input_type = classify_input(share_url, raw)
            except Exception as exc:
                raise RuntimeError(str(exc)) from exc

            if input_type == InputType.DIRECT:
                return input_type, share_url

            return process_input(
                raw,
                api_key=cfg.api_key,
                api_provider=cfg.api_provider,
                api_base_url=cfg.api_base_url,
            )

        def on_resolved(result):
            self._resolve_workers.pop(task_id, None)
            itype, data = result
            self._on_task_resolved(task_id, itype, data)
            QTimer.singleShot(0, self._pump_batch)

        def on_error(msg: str):
            self._resolve_workers.pop(task_id, None)
            self._fail_task(task_id, msg)
            QTimer.singleShot(0, self._pump_batch)

        worker = GenericWorker(resolve_task)
        worker.signals.finished.connect(on_resolved, Qt.QueuedConnection)
        worker.signals.error.connect(on_error, Qt.QueuedConnection)
        self._resolve_workers[task_id] = worker
        worker.start()

    def _on_task_resolved(self, task_id: str, input_type: InputType, result) -> None:
        task = self._queue.get(task_id)
        row = self._rows.get(task_id)
        if not task or not row:
            return

        cfg = self.config_manager.config
        output_dir = Path(cfg.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if input_type == InputType.DIRECT:
            media = MediaInfo(
                content_type=ContentType.VIDEO,
                title="direct_video",
                author="-",
                platform="direct",
                video_url=str(result),
            )
            filename = sanitize_filename(Path(str(result)).name or "video") + ".mp4"
            if not filename.lower().endswith(".mp4"):
                filename += ".mp4"
            self._begin_video_download(
                task_id, media, output_dir, filename=filename
            )
            return

        media: MediaInfo = result
        task.media = media
        task.content_type = media.content_type
        row.content_type = media.type_label
        row.author = media.author or "-"
        row.source = media.platform
        row.filename = sanitize_filename(media.title)

        self._update_table_row(task_id)
        self._append_log(
            f"解析成功 [{media.type_label}]: {media.title[:30]} | {media.author}"
        )

        if media.content_type == ContentType.IMAGE_NOTE:
            self._begin_image_download(task_id, media, output_dir)
        elif media.content_type == ContentType.VIDEO:
            ext = ".mp4"
            self._begin_video_download(
                task_id,
                media,
                output_dir,
                filename=sanitize_filename(media.title) + ext,
            )
        else:
            self._fail_task(task_id, "无法识别内容类型")

    def _begin_video_download(
        self,
        task_id: str,
        media: MediaInfo,
        output_dir: Path,
        filename: str,
    ) -> None:
        task = self._queue.get(task_id)
        row = self._rows.get(task_id)
        if not task or not row:
            return

        task.state = TaskState.DOWNLOADING
        row.content_type = "视频"
        row.filename = filename
        self._update_row_status(task_id, TaskState.DOWNLOADING.value)
        self._update_table_row(task_id)

        dt = DownloadTask(
            url=media.video_url,
            save_dir=output_dir,
            filename=filename,
            title=media.title,
            author=media.author,
            platform=media.platform,
            referer=media.referer,
        )

        def on_progress(downloaded: int, total: int, msg: str) -> None:
            status = f"下载中 {msg}"
            self._download_signals.progress.emit(task_id, status)

        def on_finished(download_task: DownloadTask) -> None:
            self._download_signals.finished.emit(task_id, download_task)

        worker = DownloadWorker(dt, on_progress, on_finished)
        row.download_worker = worker
        self._download_workers[task_id] = worker
        worker.start()

    def _begin_image_download(
        self, task_id: str, media: MediaInfo, output_dir: Path
    ) -> None:
        task = self._queue.get(task_id)
        row = self._rows.get(task_id)
        if not task or not row:
            return

        task.state = TaskState.DOWNLOADING
        row.content_type = "图文"
        row.filename = sanitize_filename(media.title)
        self._update_row_status(task_id, "下载图片...")
        self._update_table_row(task_id)

        cancel_event = threading.Event()
        row.image_cancel = cancel_event

        def work():
            def progress_callback(current: int, total: int, msg: str) -> None:
                QTimer.singleShot(
                    0,
                    lambda: self._update_row_status(
                        task_id, f"图片 {current}/{total}"
                    ),
                )

            return download_image_note(
                media,
                output_dir,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )

        def on_done(folder: Path):
            self._resolve_workers.pop(task_id, None)
            task.state = TaskState.COMPLETED
            task.output_path = str(folder)
            row.output_path = str(folder)
            row.filename = folder.name
            row.status = TaskState.COMPLETED.value
            self._finalize_duration(task_id)
            self._update_table_row(task_id)
            self._append_log(f"图文导出完成: {folder.name}")
            QTimer.singleShot(0, self._pump_batch)

        def on_error(msg: str):
            self._resolve_workers.pop(task_id, None)
            self._fail_task(task_id, msg)
            QTimer.singleShot(0, self._pump_batch)

        worker = GenericWorker(work)
        worker.signals.finished.connect(on_done, Qt.QueuedConnection)
        worker.signals.error.connect(on_error, Qt.QueuedConnection)
        self._resolve_workers[task_id] = worker
        worker.start()

    def _fail_task(self, task_id: str, error: str) -> None:
        task = self._queue.get(task_id)
        row = self._rows.get(task_id)
        if task:
            task.state = TaskState.FAILED
            task.error = error
        if row:
            row.status = TaskState.FAILED.value
            self._finalize_duration(task_id)
            self._update_table_row(task_id)
        self._append_log(f"任务失败: {error}")

    def _on_download_progress(self, task_id: str, status: str) -> None:
        self._update_row_status(task_id, status)

    def _on_download_finished(self, task_id: str, dt: DownloadTask) -> None:
        task = self._queue.get(task_id)
        row = self._rows.get(task_id)
        if not row:
            return

        if dt.save_path:
            row.output_path = str(dt.save_path)
            row.filename = dt.save_path.name
        row.status = dt.status.value

        if task:
            if dt.status == DownloadStatus.COMPLETED:
                task.state = TaskState.COMPLETED
                task.output_path = row.output_path
            elif dt.status == DownloadStatus.FAILED:
                task.state = TaskState.FAILED
                task.error = dt.error or "下载失败"
            elif dt.status == DownloadStatus.CANCELLED:
                task.state = TaskState.CANCELLED

        if dt.status == DownloadStatus.COMPLETED:
            self._finalize_duration(task_id)
        self._update_table_row(task_id)
        self._append_log(
            f"下载{dt.status.value}: {row.filename}"
            + (f" ({dt.error})" if dt.error else "")
        )
        self._download_workers.pop(task_id, None)
        QTimer.singleShot(0, self._pump_batch)

    def _add_table_row(self, row: TaskRow) -> int:
        r = self.table.rowCount()
        self.table.insertRow(r)
        row.table_index = r
        self._fill_table_row(r, row)
        return r

    def _source_label(self, platform: str) -> str:
        labels = {
            "douyin": "抖音",
            "xiaohongshu": "小红书",
            "weixin": "视频号",
            "kuaishou": "快手",
            "bilibili": "B站",
            "admuse": "腾讯妙思",
            "direct": "直链",
        }
        return labels.get(platform, platform or "-")

    def _fill_table_row(self, r: int, row: TaskRow) -> None:
        index_item = QTableWidgetItem(str(r + 1))
        index_item.setTextAlignment(Qt.AlignCenter)
        index_item.setFlags(Qt.ItemIsEnabled)
        index_item.setData(Qt.UserRole, row.task_id)
        self.table.setItem(r, COL_INDEX, index_item)

        self.table.setCellWidget(r, COL_CHECK, self._make_check_widget(row.task_id))

        type_item = QTableWidgetItem(row.content_type)
        type_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, COL_TYPE, type_item)
        filename_item = QTableWidgetItem(row.filename)
        filename_item.setData(Qt.UserRole, row.task_id)
        self.table.setItem(r, COL_FILENAME, filename_item)
        self.table.setItem(r, COL_SOURCE, QTableWidgetItem(self._source_label(row.source)))
        self.table.setItem(r, COL_AUTHOR, QTableWidgetItem(row.author or "-"))
        status_item = QTableWidgetItem(row.status)
        status_item.setData(Qt.UserRole, row.task_id)
        self.table.setItem(r, COL_STATUS, status_item)

        time_item = QTableWidgetItem(row.duration_text or "-")
        time_item.setTextAlignment(Qt.AlignCenter)
        time_item.setFlags(Qt.ItemIsEnabled)
        self.table.setItem(r, COL_TIME, time_item)

        self.table.setCellWidget(r, COL_ACTION, self._make_action_widget(row))

    def _make_check_widget(self, task_id: str, checked: bool = False) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        checkbox = CheckToggle(checked=checked)
        checkbox.setProperty("task_id", task_id)
        layout.addWidget(checkbox)
        return container

    def _get_row_checkbox(self, row: int) -> Optional[CheckToggle]:
        widget = self.table.cellWidget(row, COL_CHECK)
        if not widget:
            return None
        return widget.findChild(CheckToggle, "rowCheckBox")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(seconds))
        if total < 60:
            return f"{total}秒"
        minutes, secs = divmod(total, 60)
        if minutes < 60:
            return f"{minutes}分{secs:02d}秒"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}时{minutes:02d}分"

    def _start_task_timer(self, task_id: str) -> None:
        row = self._rows.get(task_id)
        if not row or row.started_at is not None:
            return
        row.started_at = time.monotonic()
        self._update_duration_display(task_id)

    def _update_duration_display(self, task_id: str) -> None:
        row = self._rows.get(task_id)
        if not row:
            return
        if row.duration_text:
            text = row.duration_text
        elif row.started_at is not None:
            elapsed = time.monotonic() - row.started_at
            text = self._format_duration(elapsed)
        else:
            text = "-"
        idx = self._find_row_index(task_id)
        if idx >= 0:
            time_item = self.table.item(idx, COL_TIME)
            if time_item:
                time_item.setText(text)

    def _finalize_duration(self, task_id: str) -> None:
        row = self._rows.get(task_id)
        if not row:
            return
        if row.started_at is not None:
            elapsed = time.monotonic() - row.started_at
            row.duration_text = self._format_duration(elapsed)
            row.started_at = None
        self._update_duration_display(task_id)

    def _tick_durations(self) -> None:
        for task_id, row in self._rows.items():
            if row.started_at is not None:
                self._update_duration_display(task_id)

    def _make_action_widget(self, row: TaskRow) -> QWidget:
        container = QWidget()
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignCenter)

        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)
        task_id = row.task_id

        if row.status in (
            TaskState.WAITING.value,
            TaskState.RESOLVING.value,
            TaskState.DOWNLOADING.value,
            DownloadStatus.DOWNLOADING.value,
            "下载图片...",
        ) or (
            row.status.startswith("下载中")
            or row.status.startswith("图片 ")
        ):
            btn = QPushButton("取消")
            btn.clicked.connect(lambda _, tid=task_id: self._cancel_task(tid))
            layout.addWidget(btn)
        elif row.status == TaskState.COMPLETED.value:
            btn_folder = QPushButton("文件夹")
            btn_folder.setObjectName("btnTableAction")
            btn_folder.clicked.connect(
                lambda _, p=row.output_path: self._open_folder(p)
            )
            layout.addWidget(btn_folder)
            if row.content_type != "图文" and row.output_path:
                btn_open = QPushButton("打开")
                btn_open.setObjectName("btnTableAction")
                btn_open.clicked.connect(
                    lambda _, p=row.output_path: self._open_file(p)
                )
                layout.addWidget(btn_open)
        else:
            dash = QLabel("—")
            dash.setAlignment(Qt.AlignCenter)
            layout.addWidget(dash)

        outer.addWidget(box)
        return container

    def _find_row_index(self, task_id: str) -> int:
        for r in range(self.table.rowCount()):
            for col in (COL_INDEX, COL_FILENAME, COL_STATUS):
                item = self.table.item(r, col)
                if item and item.data(Qt.UserRole) == task_id:
                    if task_id in self._rows:
                        self._rows[task_id].table_index = r
                    return r
        return -1

    def _update_row_status(self, task_id: str, status: str) -> None:
        if task_id in self._rows:
            self._rows[task_id].status = status
        idx = self._find_row_index(task_id)
        if idx >= 0:
            item = self.table.item(idx, COL_STATUS)
            if item:
                item.setText(status)

    def _update_table_row(self, task_id: str) -> None:
        row = self._rows.get(task_id)
        if not row:
            return
        idx = self._find_row_index(task_id)
        if idx < 0:
            return
        self.table.item(idx, COL_TYPE).setText(row.content_type)
        self.table.item(idx, COL_FILENAME).setText(row.filename)
        self.table.item(idx, COL_SOURCE).setText(self._source_label(row.source))
        self.table.item(idx, COL_AUTHOR).setText(row.author or "-")
        self.table.item(idx, COL_STATUS).setText(row.status)
        time_item = self.table.item(idx, COL_TIME)
        if time_item:
            time_item.setText(row.duration_text or "-")
        self.table.setCellWidget(idx, COL_ACTION, self._make_action_widget(row))

    def _cancel_task(self, task_id: str) -> None:
        worker = self._download_workers.get(task_id)
        if worker:
            worker.cancel()
        resolve_worker = self._resolve_workers.get(task_id)
        if resolve_worker:
            resolve_worker.cancel()
        row = self._rows.get(task_id)
        if row and row.image_cancel:
            row.image_cancel.set()
        task = self._queue.get(task_id)
        if task:
            task.state = TaskState.CANCELLED
        self._finalize_duration(task_id)
        self._update_row_status(task_id, TaskState.CANCELLED.value)
        self._append_log(f"已取消: {task_id}")

    def _set_all_checks(self, checked: bool) -> None:
        for r in range(self.table.rowCount()):
            checkbox = self._get_row_checkbox(r)
            if checkbox:
                checkbox.setChecked(checked)

    def _get_checked_task_ids(self) -> List[str]:
        ids: List[str] = []
        for r in range(self.table.rowCount()):
            checkbox = self._get_row_checkbox(r)
            if checkbox and checkbox.isChecked():
                item = self.table.item(r, COL_INDEX)
                tid = item.data(Qt.UserRole) if item else None
                if tid:
                    ids.append(tid)
        return ids

    def _remove_rows_by_task_ids(self, task_ids: List[str]) -> None:
        if not task_ids:
            return
        task_set = set(task_ids)
        for tid in task_ids:
            self._cancel_task(tid)
            self._download_workers.pop(tid, None)
            self._resolve_workers.pop(tid, None)
            self._queue.remove(tid)
            self._rows.pop(tid, None)
        for r in range(self.table.rowCount() - 1, -1, -1):
            item = self.table.item(r, COL_INDEX)
            if item and item.data(Qt.UserRole) in task_set:
                self.table.removeRow(r)
        self._reindex_rows()

    def _delete_selected(self) -> None:
        ids = self._get_checked_task_ids()
        if not ids:
            QMessageBox.information(self, "提示", "请先勾选要删除的条目。")
            return
        reply = QMessageBox.question(
            self,
            "删除选中",
            f"确定从列表中移除 {len(ids)} 条任务？\n（不会删除本地已下载文件）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._remove_rows_by_task_ids(ids)
        self._append_log(f"已删除 {len(ids)} 个列表项")

    def _retry_failed(self) -> None:
        failed = self._queue.failed_tasks()
        if not failed:
            QMessageBox.information(self, "提示", "没有失败的任务可重试。")
            return
        for task in failed:
            self._queue.reset_for_retry(task.task_id)
            row = self._rows.get(task.task_id)
            if row:
                row.status = TaskState.WAITING.value
                self._update_table_row(task.task_id)
        self._append_log(f"已重置 {len(failed)} 条失败任务")
        self._on_start_batch()

    def _clear_completed(self) -> None:
        to_remove = [
            tid
            for tid, row in self._rows.items()
            if row.status == TaskState.COMPLETED.value
        ]
        for i in range(self.table.rowCount() - 1, -1, -1):
            status_item = self.table.item(i, COL_STATUS)
            if status_item and status_item.text() == TaskState.COMPLETED.value:
                self.table.removeRow(i)
        for tid in to_remove:
            self._queue.remove(tid)
            self._rows.pop(tid, None)
        self._reindex_rows()
        self._append_log("已清空已完成项")

    def _reindex_rows(self) -> None:
        for r in range(self.table.rowCount()):
            for col in (COL_INDEX, COL_FILENAME):
                item = self.table.item(r, col)
                if not item:
                    continue
                task_id = item.data(Qt.UserRole)
                if task_id and task_id in self._rows:
                    self._rows[task_id].table_index = r
                    break
            index_item = self.table.item(r, COL_INDEX)
            if index_item:
                index_item.setText(str(r + 1))

    def _open_download_dir(self) -> None:
        path = self.config_manager.config.output_dir
        Path(path).mkdir(parents=True, exist_ok=True)
        self._open_folder(path)

    def _open_file(self, file_path: str) -> None:
        if not file_path or not Path(file_path).exists():
            return
        if sys.platform == "win32":
            os.startfile(file_path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", file_path])
        else:
            subprocess.run(["xdg-open", file_path])

    def _open_folder(self, folder: str) -> None:
        if not folder:
            return
        path = Path(folder)
        target = path if path.is_dir() else path.parent
        if not target.exists():
            return
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)])
        else:
            subprocess.run(["xdg-open", str(target)])

    def _show_settings(self) -> None:
        dlg = SettingsDialog(self.config_manager, self)
        if dlg.exec_() == dlg.Accepted:
            self._append_log("设置已保存")

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 ClipCleaner",
            "<h3>ClipCleaner - 多平台下载</h3>"
            "<p>版本 2.0.0</p>"
            "<p>支持短视频平台链接解析、批量下载、图文笔记导出。</p>"
            "<p>技术栈: Python + PyQt5 + requests</p>",
        )

    def _quit_app(self) -> None:
        for w in self._download_workers.values():
            w.cancel()
        for w in self._resolve_workers.values():
            w.cancel()
        for row in self._rows.values():
            if row.image_cancel:
                row.image_cancel.set()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if hasattr(self, "tray") and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "ClipCleaner",
                "程序已最小化到系统托盘",
                QSystemTrayIcon.Information,
                2000,
            )
        else:
            self._quit_app()
            event.accept()


def _install_exception_hook() -> None:
    """避免后台线程未捕获异常导致 GUI 静默退出."""
    def _hook(exc_type, exc_value, exc_tb):
        import traceback

        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("未捕获异常:\n%s", msg)
        try:
            QMessageBox.critical(
                None,
                "程序错误",
                f"发生未预期的错误，程序将保持运行。\n\n{exc_value}",
            )
        except Exception:
            pass

    sys.excepthook = _hook


def run_app() -> int:
    setup_logging()
    _install_exception_hook()

    if sys.platform == "darwin":
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("ClipCleaner")
    app.setQuitOnLastWindowClosed(False)

    ensure_icons_exist()
    icon = get_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    config_manager = ConfigManager()
    window = MainWindow(config_manager)
    window.show()
    return app.exec_()
