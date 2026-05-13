# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：认知增强系统（agent_proto PyQt5 桌面应用）

a = Analysis(
    ['agent_ui.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('agent_personas/', 'agent_personas/'),
        ('data/', 'data/'),
        ('widgets/', 'widgets/'),
    ],
    hiddenimports=[
        'agent_loop', 'agent_thinker', 'agent_actor', 'agent_memory',
        'agent_bridge', 'agent_cloud', 'agent_health', 'database',
        'widgets', 'widgets.time_slice_tab',
        'widgets.emotional_tab', 'widgets.task_tab',
        'widgets.terminal_panel', 'widgets.data_panel',
        'widgets.gantt_chart', 'widgets.heatmap',
        'PyQt5', 'win32gui', 'win32process', 'psutil', 'pyperclip', 'plyer',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='认知增强系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
