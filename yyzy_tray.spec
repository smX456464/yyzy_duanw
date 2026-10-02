# -*- mode: python ; coding: utf-8 -*-
# 月圆之夜 · 自动跳过回合（托盘版）打包配置（onedir，无窗口）
# 用法：pyinstaller --noconfirm --clean --distpath out yyzy_tray.spec
import os

ROOT = os.path.join(SPECPATH, "python")

a = Analysis(
    [os.path.join(ROOT, "yyzy_tray.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "close_watcher.py"), "."),
           (os.path.join(ROOT, "input_synth.py"), ".")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="月圆之夜自动跳过",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(SPECPATH, "release", "AutoSkip", "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AutoSkip",
)
