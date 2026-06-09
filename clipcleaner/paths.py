"""跨平台路径（Windows / macOS / Linux）."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ClipCleaner"


def get_config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
        return Path.home() / APP_NAME
    # Linux / 其他
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def get_resource_dir() -> Path:
    """打包后资源目录，开发时为项目根目录."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def get_assets_dir() -> Path:
    assets = get_resource_dir() / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    return assets


CONFIG_DIR = get_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_OUTPUT_DIR = CONFIG_DIR / "downloads"
LOG_FILE = CONFIG_DIR / "clipcleaner.log"
