# -*- mode: python ; coding: utf-8 -*-
"""
build.spec — PyInstaller 打包配置
运行：pyinstaller build.spec
"""

import os
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))

a = Analysis(
    ['desktop.py'],
    pathex=[str(BASE)],
    binaries=[],
    datas=[
        (str(BASE / 'templates'), 'templates'),
        (str(BASE / 'static'), 'static'),
    ],
    hiddenimports=[
        'flask',
        'pystray',
        'plyer',
        'psutil',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'win32gui',
        'win32process',
        'win32api',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='认知增强系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                          # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(BASE / 'static' / 'icon.ico'),
)
