#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Pure planning logic for smart capture save (detect-before-write).

The capture worker holds every burst frame in RAM (defer-save). Instead of
writing all of them to ``captures\\`` and then copying the injection window
back out, smart save detects the window FIRST (same detection code as always)
and writes only the window frames, directly into the injection-images run
folder. This module is the camera-free part: window planning, the
build_result-compatible metadata dict, and the injection_meta.json payload.
Kept free of SDK/Tk imports so it is unit-testable headless.
"""

import numpy as np

from hsc import injection_extract


def plan_window(signal, frame_getter, n, before, after):
    """Detect the injection and return ``(bounds, window)``.

    ``bounds`` is ``(start, end, peak)`` from the unchanged
    ``detect_bounds_with_presence``; ``window`` is ``(copy_start, copy_end)``
    using exactly ``build_result``'s clamp math. Returns ``(None, None)``
    when no injection is present (caller falls back to a full legacy save).
    """
    bounds = injection_extract.detect_bounds_with_presence(
        np.asarray(signal, dtype=np.float64), frame_getter, n)
    if bounds is None:
        return None, None
    start, end, _ = bounds
    window = (max(0, start - int(before)), min(int(n) - 1, end + int(after)))
    return bounds, window


def make_result(frame_names, signal, bounds, window, source_dir, dest_dir,
                before, after, method):
    """Metadata dict with the exact key set ``build_result`` returns, so the
    GUI's ``_on_extract_done`` consumes it unchanged."""
    signal = np.asarray(signal, dtype=np.float64)
    start, end, peak = bounds
    copy_start, copy_end = window
    return {
        "source_dir": str(source_dir),
        "dest_dir": str(dest_dir),
        "method": method,
        "total_frames": len(frame_names),
        "peak_index": peak,
        "peak_frame": frame_names[peak],
        "peak_value": int(signal[peak]),
        "injection_start_frame": frame_names[start],
        "injection_end_frame": frame_names[end],
        "injection_count": end - start + 1,
        "copy_start_frame": frame_names[copy_start],
        "copy_end_frame": frame_names[copy_end],
        "selected_count": copy_end - copy_start + 1,
        "before": before,
        "after": after,
        "copied": True,
    }


def make_meta(bounds, window, method):
    """injection_meta.json payload (same schema as injection_extract's)."""
    start, _end, _peak = bounds
    copy_start, copy_end = window
    return {
        "pre_frames": int(start - copy_start),
        "onset_index": int(start),
        "copy_start": int(copy_start),
        "copy_end": int(copy_end),
        "method": str(method),
    }
