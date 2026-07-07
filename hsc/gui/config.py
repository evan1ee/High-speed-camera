#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared GUI constants (output folders, presets) and the app-log writer."""

import time

from hsc.app_paths import data_root


ROOT = data_root()
LOG_FILE = ROOT / "app.log"
INJECTION_DIR = ROOT / "injection images"
MEASURE_DIR = ROOT / "measure"
BLOCK_DIR = MEASURE_DIR / "angle_block"
SCALE_DIR = MEASURE_DIR / "block"
REFERENCE_DIR = MEASURE_DIR / "reference"
ASPECT_PRESETS = ("1:1", "2:1", "4:3", "16:9", "320x240")
IMAGE_EXTENSIONS = (".bmp", ".png", ".jpg", ".tif")


def log_to_file(text):
    """Append a timestamped message to ``data_root()/app.log``.

    The frozen build is windowed (``console=False``) so stdout is discarded;
    this is the only persistent record of GUI activity. Wrapped so that logging
    can never break the GUI (a full disk / locked file is swallowed silently).
    """
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = str(text).rstrip("\n")
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {line}\n")
    except Exception:
        pass
