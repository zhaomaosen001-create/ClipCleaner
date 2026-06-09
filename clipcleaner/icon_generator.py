"""应用图标生成（内嵌，无需外部脚本）."""

from __future__ import annotations

import logging
import platform
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from clipcleaner.paths import get_assets_dir

logger = logging.getLogger(__name__)

SIZES = [16, 32, 48, 64, 128, 256, 512, 1024]


def _draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = size // 16
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=size // 5,
        fill=(52, 152, 219, 255),
    )
    cx, cy = size // 2, size // 2
    tri = size // 3
    draw.polygon(
        [
            (cx - tri // 3, cy - tri // 2),
            (cx - tri // 3, cy + tri // 2),
            (cx + tri // 2, cy),
        ],
        fill=(255, 255, 255, 240),
    )
    check_size = size // 5
    ox = size - margin - check_size
    oy = margin + check_size // 4
    draw.ellipse(
        [ox, oy, ox + check_size, oy + check_size],
        fill=(46, 204, 113, 255),
    )
    lw = max(2, size // 64)
    draw.line(
        [
            (ox + check_size * 0.25, oy + check_size * 0.55),
            (ox + check_size * 0.42, oy + check_size * 0.72),
            (ox + check_size * 0.78, oy + check_size * 0.32),
        ],
        fill=(255, 255, 255, 255),
        width=lw,
    )
    return img


def generate_all(assets_dir: Path | None = None) -> Path:
    """生成 PNG / ICO / ICNS（macOS）."""
    assets = assets_dir or get_assets_dir()
    assets.mkdir(parents=True, exist_ok=True)

    images = []
    for s in SIZES:
        img = _draw_icon(s)
        img.save(assets / f"icon_{s}.png")
        images.append(img)
    images[-1].save(assets / "icon.png")

    images[0].save(
        assets / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[1:],
    )

    if platform.system() == "Darwin":
        _generate_icns(assets)

    logger.info("图标已生成: %s", assets)
    return assets


def _generate_icns(assets: Path) -> None:
    iconset = assets / "ClipCleaner.iconset"
    iconset.mkdir(exist_ok=True)
    pairs = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for src_size, name in pairs:
        src = assets / f"icon_{src_size}.png"
        if src.exists():
            (iconset / name).write_bytes(src.read_bytes())
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(assets / "icon.icns")],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("ICNS 生成失败: %s", exc)
