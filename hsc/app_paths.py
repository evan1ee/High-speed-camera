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
    """Base folder for user output written at runtime (``captures``,
    ``injection images``, ``measure``, ``settings``). Next to the
    .exe when frozen; ``<root>/data`` from source (created on demand)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    root = Path(__file__).resolve().parents[1] / "data"
    root.mkdir(exist_ok=True)
    return root


def settings_path(name: str) -> Path:
    """Path of a rig-settings file (``calibration.json``,
    ``reference_lines.json``) inside ``<root>/settings`` -- next to ``data/``
    from source, next to the .exe when frozen.

    Files used to live at the ``data_root()`` top level and then in
    ``data/settings``; if the new path does not exist yet but an old one
    does, the old file (and its ``.bak``) is migrated in, so existing rigs
    keep their calibration after upgrading.
    """
    if is_frozen():
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parents[1]
    folder = base / "settings"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    for old in (data_root() / "settings" / name, data_root() / name):
        if path.exists() or not old.exists() or old == path:
            continue
        try:
            old.replace(path)
            old_bak = old.with_name(old.name + ".bak")
            if old_bak.exists():
                old_bak.replace(folder / old_bak.name)
        except OSError:
            pass
    return path
