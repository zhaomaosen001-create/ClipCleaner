# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - ClipCleaner (macOS .app)."""

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

icon_path = project_root / "assets" / "icon.icns"
if not icon_path.exists():
    icon_path = project_root / "assets" / "icon.ico"

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
    excludes=['torch', 'torchvision', 'mmcv'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ClipCleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ClipCleaner',
)

app = BUNDLE(
    coll,
    name='ClipCleaner.app',
    icon=str(icon_path) if icon_path.exists() else None,
    bundle_identifier='com.clipcleaner.app',
    info_plist={
        'NSHighResolutionCapable': 'True',
        'CFBundleDisplayName': 'ClipCleaner',
        'CFBundleName': 'ClipCleaner',
        'CFBundleShortVersionString': '2.0.0',
    },
)
