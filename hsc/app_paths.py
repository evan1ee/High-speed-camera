#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Path resolution that works both from source and from a PyInstaller build.

Two distinct roots are needed:

- **resource_root()** -- where the *bundled, read-only* files live: the camera
  SDK Python wrapper (``Development/.../MVSDK``), the ``Runtime`` DLL folder and
  ``injection_scan.exe``. When frozen these are unpacked into ``sys._MEIPASS``.
- **data_root()** -- where the app *writes* user output (``captures``,
  ``injection images``, ``measure``). When frozen this is the folder that holds
  the .exe, so results land next to the app the user can see, not in a temp dir.

From source (not frozen) both roots are just this file's directory.
"""

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Base folder for bundled read-only resources (SDK, Runtime DLLs, helper exe)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]


def data_root() -> Path:
    """Base folder for user output written at runtime (next to the .exe when frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
