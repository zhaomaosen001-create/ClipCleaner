#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动生成 ClipCleaner 应用图标（PNG / ICO / ICNS）."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clipcleaner.icon_generator import generate_all  # noqa: E402

if __name__ == "__main__":
    out = generate_all(ROOT / "assets")
    print(f"图标生成完成: {out}")
