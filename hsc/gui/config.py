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
REFERENCE_DIR = ROOT / "reference line"
ASPECT_PRESETS = ("1:1", "2:1", "4:3", "16:9", "320x240")
IMAGE_EXTENSIONS = (".bmp", ".png", ".jpg", ".tif")
# Fixed padding around a detected injection (frames kept before the onset /
# after the end). Former "Frames before/after injection" entry fields.
PAD_BEFORE = 30
PAD_AFTER = 30
# Selectable capture ROIs, shortest-readout last. The camera free-runs, and
# its rate is set by how many ROWS it reads, not by exposure -- measured on the
# rig 2026-08-12 with zero dropped frames in every case. A shorter ROI is the
# only way to resolve the injection's opening transient, which spans ~2.9 ms:
# barely 3 frames at 1048 fps but ~7.6 at 2624.
#
# mm/px is a property of the optics, so cropping does NOT change it -- the
# stored calibration stays valid at any of these sizes.
#: 320x64 was measured (2624 fps) and then WITHDRAWN. It crops into the barrel
#: -- 48 usable rows against 79 at both sizes below -- and the piston in that
#: view is grey rather than black, with a collar that detaches mid-stroke. No
#: single edge rule held across the stroke; the two-stage rule in piston_track
#: (SHORT_ROI_ROWS) does, but the view is not worth the fragility for 1.5x.
#: To use that frame rate, re-aim the camera so the barrel FILLS the short
#: frame instead of being cropped mid-way, then add the preset back.
CAPTURE_ROIS = ("320x240", "320x120")
ROI_FPS = {"320x240": 1048, "320x120": 1798}
#: Longest exposure that still fits inside the frame period, so the ROI runs at
#: its full rate. Exceeding it costs BOTH speed and contrast: at 320x64 the
#: default 500 us dropped the rate to 1830 fps AND lifted the piston from
#: black (min 4) to grey (min 38, not one pixel below 30), which left the
#: detector nothing to lock onto -- two rig runs on 2026-08-13 failed that way.
ROI_MAX_EXPOSURE_US = {"320x240": 950, "320x120": 550}
DEFAULT_ROI = "320x240"


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
