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

import json
from pathlib import Path

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


def write_meta(dest_dir, bounds, window, method):
    """Write injection_meta.json (best-effort -- metadata, never a failure)."""
    try:
        (Path(dest_dir) / "injection_meta.json").write_text(
            json.dumps(make_meta(bounds, window, method), indent=2),
            encoding="utf-8")
    except OSError:
        pass


def replay(source_dir, before=30, after=30):
    """Re-run the smart-save decision on an existing burst folder on disk.

    Uses the same signal back-ends and downsampled presence frames as the
    offline extractor, so the result shows exactly what smart save WOULD have
    kept for this burst. Returns {"bounds", "window", "names"}.
    """
    files = injection_extract.list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")
    signal, _method = injection_extract.compute_motion_signal_best(files)
    getter = injection_extract.raw_downsample_getter(files)
    if getter is None:                       # non-BMP burst: decode via PIL
        from PIL import Image
        ds = injection_extract.DOWNSAMPLE
        def getter(i):
            img = np.asarray(Image.open(files[i]).convert("L"), dtype=np.int16)
            return img[::ds, ::ds]
    bounds, window = plan_window(signal, getter, len(files), before, after)
    names = ([] if window is None
             else [f.name for f in files[window[0] : window[1] + 1]])
    return {"bounds": bounds, "window": window, "names": names}


def _main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Replay the smart-save decision on an existing burst.")
    parser.add_argument("source", help="a data\\captures\\<run> folder")
    parser.add_argument("--before", type=int, default=30)
    parser.add_argument("--after", type=int, default=30)
    parser.add_argument("--compare", action="store_true",
                        help="also run the legacy detector and diff the windows")
    args = parser.parse_args()

    rep = replay(args.source, args.before, args.after)
    if rep["bounds"] is None:
        print("no injection detected (legacy full save would apply)")
        return
    start, end, peak = rep["bounds"]
    print(f"bounds: start={start} end={end} peak={peak}")
    print(f"window: frames {rep['window'][0]}..{rep['window'][1]} "
          f"({len(rep['names'])} files kept of "
          f"{len(injection_extract.list_frames(args.source))})")
    if args.compare:
        legacy = injection_extract.extract_injection(
            args.source, before=args.before, after=args.after, copy=False)
        same = (legacy["copy_start_frame"] == rep["names"][0]
                and legacy["copy_end_frame"] == rep["names"][-1])
        print("IDENTICAL to legacy extraction" if same else
              f"DIFFERS: legacy {legacy['copy_start_frame']}.."
              f"{legacy['copy_end_frame']}")


if __name__ == "__main__":
    _main()
