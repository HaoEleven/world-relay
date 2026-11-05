# -*- mode: python ; coding: utf-8 -*-

import importlib.util
from pathlib import Path


project_root = Path(SPECPATH)
app_info_spec = importlib.util.spec_from_file_location(
    "world_relay_app_info", project_root / "app_info.py"
)
app_info = importlib.util.module_from_spec(app_info_spec)
app_info_spec.loader.exec_module(app_info)
release_directory = f"WorldRelay-v{app_info.VERSION}"

a = Analysis(
    [str(project_root / "desktop.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(project_root / "static"), "static")],
    hiddenimports=[
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "cefpython3"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WorldRelay",
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
    icon=str(project_root / "assets" / "world_relay.ico"),
    version=str(project_root / "world_relay_version.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=release_directory,
)
