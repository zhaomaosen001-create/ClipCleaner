"""应用图标加载."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt5.QtGui import QIcon

from clipcleaner.paths import get_assets_dir, get_resource_dir

logger = logging.getLogger(__name__)


def ensure_icons_exist() -> None:
    """若图标不存在则自动生成."""
    assets = get_assets_dir()
    if (assets / "icon.png").exists():
        return
    try:
        from clipcleaner.icon_generator import generate_all

        generate_all(assets)
    except Exception as exc:
        logger.warning("图标自动生成失败: %s", exc)


def get_app_icon() -> QIcon:
    """获取跨平台应用图标."""
    assets = get_resource_dir() / "assets"
    if not assets.exists():
        assets = get_assets_dir()

    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(assets / "icon.icns")
    candidates.extend([
        assets / "icon.ico",
        assets / "icon.png",
        assets / "icon_256.png",
        assets / "icon_128.png",
    ])

    for path in candidates:
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon

    return QIcon()
