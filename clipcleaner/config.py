"""应用配置持久化."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from clipcleaner.paths import (
    APP_NAME,
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_OUTPUT_DIR,
    LOG_FILE,
)

logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    api_key: str = ""
    api_provider: str = "auto"  # auto | builtin | douyin_wtf | custom
    api_base_url: str = ""  # custom API 地址，支持 {url} 占位符
    output_dir: str = ""
    max_concurrent_downloads: int = 2
    window_geometry: Optional[List[int]] = None

    def __post_init__(self) -> None:
        if not self.output_dir:
            self.output_dir = str(DEFAULT_OUTPUT_DIR)
        if self.max_concurrent_downloads < 1:
            self.max_concurrent_downloads = 1
        if self.max_concurrent_downloads > 8:
            self.max_concurrent_downloads = 8

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)


class ConfigManager:
    """读写配置文件."""

    def __init__(self, config_file: Path = CONFIG_FILE) -> None:
        self.config_file = config_file
        self._config = AppConfig()
        self._ensure_dirs()
        self.load()

    def _ensure_dirs(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def config(self) -> AppConfig:
        return self._config

    def load(self) -> AppConfig:
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if hasattr(self._config, key):
                        setattr(self._config, key, value)
                self._config.__post_init__()
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("加载配置失败，使用默认值: %s", exc)
        return self._config

    def save(self) -> None:
        self._ensure_dirs()
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(asdict(self._config), f, ensure_ascii=False, indent=2)

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        self.save()


def setup_logging() -> logging.Logger:
    """初始化日志."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger(APP_NAME)

    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return logging.getLogger(APP_NAME)
