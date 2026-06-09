#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClipCleaner 入口."""

import sys


def main() -> int:
    try:
        from clipcleaner.gui.main_window import run_app

        return run_app()
    except ImportError as exc:
        print(f"依赖缺失: {exc}")
        print("请运行: pip install -r requirements.txt")
        return 1


if __name__ == "__main__":
    sys.exit(main())
