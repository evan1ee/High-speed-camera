# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the High Speed Camera GUI.

Produces a one-folder distribution in ``dist/HighSpeedCamera`` that can be
zipped and copied to another Windows PC. Build with:

    pyinstaller HighSpeedCamera.spec --noconfirm

The vendor camera SDK loads ``MVSDKmd.dll`` by a path *relative* to the SDK
wrapper folder (``../../../../../Runtime/x64/MVSDKmd.dll``), so the original
``Development/.../MVSDK`` and ``Runtime/x64`` directory structure is preserved
inside the bundle. ``app_paths.resource_root()`` resolves to that bundle at
runtime; user output (captures / injection images / measure) is written next to
the .exe via ``app_paths.data_root()``.
"""

from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# scikit-learn pulls modules in lazily; collect them explicitly. scipy / numpy /
# cv2 / PIL are handled by their bundled hooks.
hiddenimports = collect_submodules("sklearn")
datas = collect_data_files("sklearn")
datas += [("injection_scan.exe", ".")]

a = Analysis(
    ["capture_gui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pytest"],
    noarchive=False,
)

# Bundle the vendor SDK wrapper + Runtime DLLs, preserving relative structure.
a.datas += Tree("Runtime/x64", prefix="Runtime/x64")
a.datas += Tree(
    "Development/Samples/Python/IMV/MVSDK",
    prefix="Development/Samples/Python/IMV/MVSDK",
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HighSpeedCamera",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HighSpeedCamera",
)
