#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Path resolution that works both from source and from a PyInstaller build.

Two distinct roots are needed:

- **resource_root()** -- where the *bundled, read-only* files live under
  ``vendor/``: the camera SDK Python wrapper (``Development/.../MVSDK``), the
  ``Runtime`` DLL folder and ``bin/injection_scan.exe``. When frozen these are
  unpacked into ``sys._MEIPASS/vendor``.
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
    """Folder containing the bundled read-only resources: ``Development/`` (SDK
    wrapper), ``Runtime/`` (DLLs) and ``bin/`` (helper exe). ``<root>/vendor``
    from source; ``<_MEIPASS>/vendor`` when frozen (the spec bundles with a
    matching ``vendor/`` prefix)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        base = Path(__file__).resolve().parents[1]
    return base / "vendor"


def data_root() -> Path:
    """Base folder for user output written at runtime (next to the .exe when frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
