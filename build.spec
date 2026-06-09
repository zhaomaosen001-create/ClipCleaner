# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - ClipCleaner (Windows .exe)."""

import importlib.util
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)
_hi = importlib.util.spec_from_file_location(
    "build_hiddenimports",
    project_root / "scripts" / "build_hiddenimports.py",
)
_hi_mod = importlib.util.module_from_spec(_hi)
_hi.loader.exec_module(_hi_mod)

a = Analysis(
    ['main.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / 'clipcleaner' / 'gui' / 'styles.qss'), 'clipcleaner/gui'),
        (str(project_root / 'assets'), 'assets'),
    ],
    hiddenimports=_hi_mod.HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'mmcv'],  # AI 模块按需分发
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ClipCleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / 'assets' / 'icon.ico')
    if (project_root / 'assets' / 'icon.ico').exists()
    else None,
)
