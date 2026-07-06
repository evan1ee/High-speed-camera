# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the High Speed Camera GUI.

Produces a one-folder distribution in ``dist/HighSpeedCamera`` that can be
zipped and copied to another Windows PC. Build from the project root with:

    packaging\\build_exe.bat

The vendor camera SDK loads ``MVSDKmd.dll`` by a path *relative* to the SDK
wrapper folder (``../../../../../Runtime/x64/MVSDKmd.dll``), so ``Development``
and ``Runtime`` are bundled as siblings under a ``vendor/`` prefix - exactly
mirroring the source tree. ``hsc.app_paths.resource_root()`` resolves to
``<_MEIPASS>/vendor`` at runtime; user output is written next to the .exe via
``hsc.app_paths.data_root()``.
"""

import os

from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH is the directory holding this spec (packaging/); the project root is
# its parent. All input paths are anchored there so the build works no matter
# where pyinstaller is invoked from.
ROOT = os.path.dirname(SPECPATH)  # noqa: F821 - SPECPATH injected by PyInstaller

# scikit-learn pulls modules in lazily; collect them explicitly. scipy / numpy /
# cv2 / PIL are handled by their bundled hooks.
hiddenimports = collect_submodules("sklearn")
datas = collect_data_files("sklearn")
datas += [(os.path.join(ROOT, "vendor", "bin", "injection_scan.exe"), "vendor/bin")]

a = Analysis(
    [os.path.join(ROOT, "run_gui.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pytest"],
    noarchive=False,
)

# Bundle the vendor SDK wrapper + Runtime DLLs, preserving relative structure
# under the same vendor/ prefix used in the source tree.
a.datas += Tree(os.path.join(ROOT, "vendor", "Runtime", "x64"),
                prefix="vendor/Runtime/x64")
a.datas += Tree(
    os.path.join(ROOT, "vendor", "Development", "Samples", "Python", "IMV", "MVSDK"),
    prefix="vendor/Development/Samples/Python/IMV/MVSDK",
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
