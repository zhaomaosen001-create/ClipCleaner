"""Playwright 浏览器检测、自动安装与启动."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


def is_playwright_installed() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def install_chromium(progress: Optional[ProgressFn] = None) -> None:
    """下载 Playwright 自带 Chromium."""
    if progress:
        progress("正在下载 Playwright Chromium（首次约 1–3 分钟）...")
    logger.info("执行: %s -m playwright install chromium", sys.executable)
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Playwright 浏览器安装失败:\n{err}")
    if progress:
        progress("Chromium 安装完成")


def launch_chromium(playwright: Any, progress: Optional[ProgressFn] = None):
    """
    启动 Chromium，按顺序尝试：
    1. 自带 headless Chromium
    2. 系统 Google Chrome (channel=chrome)
    3. 自动安装后再试
    4. 系统 Chrome / Edge 回退
    """
    last_error: Optional[Exception] = None

    def _try_launch(**kwargs):
        nonlocal last_error
        try:
            browser = playwright.chromium.launch(**kwargs)
            logger.info("浏览器启动成功: %s", kwargs)
            return browser
        except Exception as exc:
            last_error = exc
            logger.warning("浏览器启动失败 (%s): %s", kwargs, exc)
            return None

    # 1. 自带 Chromium
    browser = _try_launch(headless=True)
    if browser:
        return browser

    # 2. 系统 Chrome（Mac 常见已安装）
    if progress:
        progress("尝试使用本机 Google Chrome...")
    browser = _try_launch(headless=True, channel="chrome")
    if browser:
        return browser

    # 3. 自动安装 Playwright Chromium
    if _is_missing_executable(last_error):
        try:
            install_chromium(progress)
            browser = _try_launch(headless=True)
            if browser:
                return browser
        except Exception as install_exc:
            logger.error("自动安装失败: %s", install_exc)
            last_error = install_exc

    # 4. 再次尝试系统浏览器
    for channel in ("chrome", "msedge", "chromium"):
        browser = _try_launch(headless=True, channel=channel)
        if browser:
            return browser

    msg = (
        "无法启动浏览器。请在本机终端执行：\n\n"
        f"  {sys.executable} -m pip install playwright\n"
        f"  {sys.executable} -m playwright install chromium\n\n"
        "或确保已安装 Google Chrome 后重试。"
    )
    if last_error:
        msg += f"\n\n原始错误:\n{last_error}"
    raise RuntimeError(msg)


def _is_missing_executable(exc: Optional[Exception]) -> bool:
    if exc is None:
        return True
    text = str(exc)
    return (
        "Executable doesn't exist" in text
        or "Please run the following command" in text
        or "playwright install" in text.lower()
    )
