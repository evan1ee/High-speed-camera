#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Detect the injection event inside a high-speed burst and copy the relevant
frames (with padding) into an "injection images" folder.

A needle-free injection lasts ~200 ms but the burst records 3000+ frames.
Only the ~200-300 frames around the high-pressure jet are interesting.

Detection strategy
------------------
The scene drifts slowly (lighting / water level), so comparing each frame to a
static background is unreliable. Instead we use the *temporal* difference: for
each frame we count how many pixels changed by more than ``diff_thresh`` versus
the previous frame. Slow drift contributes almost nothing, while the sudden
appearance and turbulence of the jet produces a large, sharp spike.

The injection interval is found by anchoring on the peak of that signal and
expanding outward while the signal stays above an adaptive threshold
(a small fraction of the peak). The copy window then adds ``before`` frames
ahead of the injection start and ``after`` frames past the injection end.

Performance
-----------
Computing the motion signal is the slow part (thousands of files). Three
back-ends are tried in order, all producing the *same* signal:

1. ``injection_scan.exe`` -- a compiled C++/OpenMP scanner (fastest, ~20x).
2. A NumPy reader that parses the raw uncompressed BMP bytes in parallel
   threads (no PIL overhead, ~3x).
3. PIL decoding every frame (works for any image format; the fallback).
"""

import argparse
import json
import os
import shutil
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image


IMAGE_EXTENSIONS = (".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff")
DEST_FOLDER_NAME = "injection images"
DIFF_THRESH = 25

# Jet-presence (end-of-injection) detection parameters. The temporal diff finds
# the onset reliably, but a steady/laminar jet has little frame-to-frame change
# while still clearly visible -- so the *end* is found from how much each frame
# still differs from the pre-injection background inside the jet region.
DOWNSAMPLE = 4          # spatial step for the cheap presence signal
PRESENCE_DIFF = 25      # per-pixel change vs. background to count as "wet"
MASK_DIFF = 40          # build the jet mask from the peak frame
END_RESIDUAL_K = 1.8    # jet ends when presence settles to this x the trough floor
END_SMOOTH_WIN = 21     # moving-average window for the presence signal
END_HOLD = 25           # frames presence must stay low to confirm the jet ended
END_MIN_GAP = 8         # don't look for the end right at the peak
from hsc.app_paths import resource_root

HERE = resource_root()
CPP_EXE = HERE / "bin" / ("injection_scan.exe" if os.name == "nt" else "injection_scan")


def list_frames(source_dir):
    """Return image files in *source_dir* sorted by their zero-padded name."""
    source_dir = Path(source_dir)
    frames = [
        p
        for p in source_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(frames, key=lambda p: p.name)


# ----------------------------------------------------------------------
# Raw BMP helpers (uncompressed 8-bit)
# ----------------------------------------------------------------------
def _bmp_info(path):
    """Return (pixel_offset, width, abs_height, bpp, bottom_up) or None.

    ``bottom_up`` is True for the standard positive-biHeight layout (rows
    stored bottom row first -- what cv2.imwrite produces); the IMV SDK saves
    negative-biHeight top-down files. Raw readers must flip bottom-up rows
    after the top-down reshape or the image comes out upside down.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(54)
        if len(head) < 54 or head[:2] != b"BM":
            return None
        offset = struct.unpack_from("<I", head, 10)[0]
        width = struct.unpack_from("<i", head, 18)[0]
        height = struct.unpack_from("<i", head, 22)[0]
        bpp = struct.unpack_from("<H", head, 28)[0]
        # Reject degenerate dimensions before they reach numpy reshape (a
        # negative/zero width would otherwise slip through as bad geometry).
        if width <= 0 or height == 0:
            return None
        return offset, width, abs(height), bpp, height > 0
    except OSError:
        return None


def _read_raw_pixels(path, offset, npix, height, width, bottom_up=False):
    data = np.fromfile(path, dtype=np.uint8)
    if data.size < offset + npix:
        raise ValueError(f"Short BMP: {path}")
    frame = data[offset : offset + npix].reshape(height, width)
    if bottom_up:
        frame = frame[::-1]
    return frame.astype(np.int16)


# ----------------------------------------------------------------------
# Motion signal back-ends (all return the same per-frame signal)
# ----------------------------------------------------------------------
def scan_with_cpp(source_dir, n_expected, diff_thresh=25):
    """Run the compiled C++ scanner. Returns a float signal or None on failure."""
    if not CPP_EXE.exists():
        return None
    try:
        proc = subprocess.run(
            [str(CPP_EXE), str(source_dir), str(diff_thresh)],
            capture_output=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        signal = np.frombuffer(proc.stdout, dtype=np.int32).astype(np.float64)
        if signal.size != n_expected:
            return None
    except ValueError:
        # Garbled stdout (byte count not a multiple of 4) -> fall back to the
        # Python back-ends instead of crashing the whole extraction.
        return None
    return signal


def compute_motion_signal_raw(files, diff_thresh=25, workers=8, chunk=128, progress=None):
    """Full-resolution motion signal using raw BMP bytes, read in parallel.

    Returns the signal, or None if the frames are not uniform 8-bit BMPs.
    """
    info = _bmp_info(files[0])
    if info is None or info[3] != 8:
        return None
    offset, width, height, _, bottom_up = info
    npix = width * height

    n = len(files)
    signal = np.zeros(n, dtype=np.float64)

    def do_chunk(start):
        end = min(start + chunk, n)
        prev = _read_raw_pixels(files[start - 1], offset, npix, height, width,
                                bottom_up)
        out = []
        for i in range(start, end):
            cur = _read_raw_pixels(files[i], offset, npix, height, width,
                                   bottom_up)
            out.append((i, float(np.count_nonzero(np.abs(cur - prev) > diff_thresh))))
            prev = cur
        return out

    starts = list(range(1, n, chunk))
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for chunk_result in pool.map(do_chunk, starts):
                for i, value in chunk_result:
                    signal[i] = value
                done += len(chunk_result)
                if progress is not None:
                    progress(min(done + 1, n), n)
    except (OSError, ValueError):
        return None
    return signal


def compute_motion_signal(files, diff_thresh=25, progress=None):
    """PIL fallback: decode every frame and count changed pixels vs. previous."""
    n = len(files)
    signal = np.zeros(n, dtype=np.float64)
    if n == 0:
        return signal

    prev = np.asarray(Image.open(files[0]).convert("L"), dtype=np.int16)
    step = max(1, n // 100)
    for i in range(1, n):
        cur = np.asarray(Image.open(files[i]).convert("L"), dtype=np.int16)
        signal[i] = np.count_nonzero(np.abs(cur - prev) > diff_thresh)
        prev = cur
        if progress is not None and (i % step == 0 or i == n - 1):
            progress(i + 1, n)
    return signal


def compute_motion_signal_best(files, diff_thresh=25, progress=None):
    """Compute the motion signal with the fastest available back-end.

    Returns ``(signal, method_name)``.
    """
    source_dir = files[0].parent
    all_bmp = all(f.suffix.lower() == ".bmp" for f in files)

    if all_bmp:
        signal = scan_with_cpp(source_dir, len(files), diff_thresh)
        if signal is not None:
            if progress is not None:
                progress(len(files), len(files))
            return signal, "C++ (OpenMP)"

        signal = compute_motion_signal_raw(files, diff_thresh, progress=progress)
        if signal is not None:
            return signal, "Python raw BMP"

    return compute_motion_signal(files, diff_thresh, progress=progress), "Python PIL"


# ----------------------------------------------------------------------
# Detection + extraction
# ----------------------------------------------------------------------
def detect_injection_bounds(signal, frac=0.005, abs_floor=30.0, gap=5, min_peak=300.0):
    """Find (injection_start, injection_end, peak_index) from a motion signal.

    Returns ``None`` if no clear injection is present.
    """
    n = len(signal)
    if n < 3:
        return None

    peak = int(np.argmax(signal))
    peak_value = float(signal[peak])
    if peak_value < min_peak:
        return None

    threshold = max(abs_floor, frac * peak_value)

    def walk(step):
        i = peak
        miss = 0
        last = peak
        while 0 <= i < n:
            if signal[i] > threshold:
                last = i
                miss = 0
            else:
                miss += 1
                if miss > gap:
                    break
            i += step
        return last

    start = walk(-1)
    end = walk(1)
    return start, end, peak


def _moving_average(x, window):
    if window <= 1 or len(x) < window:
        return np.asarray(x, dtype=np.float64)
    kernel = np.ones(window, dtype=np.float64) / window
    return np.convolve(np.asarray(x, dtype=np.float64), kernel, mode="same")


def raw_downsample_getter(files):
    """Return a function i -> downsampled int16 frame, reading raw BMP bytes.

    Returns None if the frames are not uniform 8-bit BMPs.
    """
    info = _bmp_info(files[0])
    if info is None or info[3] != 8:
        return None
    offset, width, height, _, bottom_up = info
    npix = width * height
    ds_shape = (
        (height + DOWNSAMPLE - 1) // DOWNSAMPLE,
        (width + DOWNSAMPLE - 1) // DOWNSAMPLE,
    )

    def get(i):
        try:
            data = np.fromfile(files[i], dtype=np.uint8)
            if data.size < offset + npix:
                raise ValueError(f"Short BMP: {files[i]}")
            frame = data[offset : offset + npix].reshape(height, width)
            if bottom_up:
                frame = frame[::-1]
            return frame[::DOWNSAMPLE, ::DOWNSAMPLE].astype(np.int16)
        except (OSError, ValueError):
            # A single unreadable/truncated frame contributes nothing (mirrors
            # the C++ scanner leaving signal[i]=0), rather than crashing the scan.
            return np.zeros(ds_shape, dtype=np.int16)

    return get


def detect_bounds_with_presence(
    signal,
    frame_getter,
    n,
    frac=0.005,
    abs_floor=30.0,
    gap=5,
    min_peak=300.0,
    pre=120,
    pre_gap=20,
    scan_cap=1500,
    residual_k=END_RESIDUAL_K,
    end_rule="presence",
):
    """Find (start, end, peak) using the temporal signal for onset and a
    jet-region presence signal for the end (so a steady jet is not cut early).

    ``frame_getter(i)`` must return a 2-D int16 (downsampled) frame.
    Returns ``None`` if no clear injection is present.

    ``end_rule`` selects how the end is found:

    * ``"presence"`` (default) -- the jet is gone when presence inside the jet
      mask settles back toward the pre-onset background. Right for a jet in
      air, which clears.
    * ``"temporal"`` -- the event is over when frame-to-frame motion stops.
      Right when the scene STAYS changed afterwards (a jet fired into a gel
      block leaves the gel deformed and dyed), because presence then never
      returns and its trough no longer means "jet gone".
    """
    if end_rule not in ("presence", "temporal"):
        raise ValueError(
            f"end_rule must be 'presence' or 'temporal', got {end_rule!r}"
        )
    n = int(n)
    if n < 3:
        return None
    peak = int(np.argmax(signal))
    if float(signal[peak]) < min_peak:
        return None

    threshold = max(abs_floor, frac * float(signal[peak]))

    # Onset: walk left on the temporal signal while it stays elevated.
    def walk_left():
        i = peak
        miss = 0
        last = peak
        while i >= 0:
            if signal[i] > threshold:
                last = i
                miss = 0
            else:
                miss += 1
                if miss > gap:
                    break
            i -= 1
        return last

    def walk_right_temporal():
        i = peak
        miss = 0
        last = peak
        while i < n:
            if signal[i] > threshold:
                last = i
                miss = 0
            else:
                miss += 1
                if miss > gap:
                    break
            i += 1
        return last

    start = walk_left()

    if end_rule == "temporal":
        # The scene does not clear, so skip the presence machinery entirely.
        return start, walk_right_temporal(), peak

    # Background from frames just before the onset.
    lo = max(0, start - pre)
    hi = max(lo + 1, start - pre_gap)
    if hi <= lo:
        lo, hi = 0, min(n, max(1, start))
    bg = np.median(np.stack([frame_getter(i) for i in range(lo, hi)]), axis=0)

    mask = np.abs(frame_getter(peak) - bg) > MASK_DIFF
    if int(mask.sum()) < 10:
        # No usable jet region -> fall back to the temporal end.
        return start, walk_right_temporal(), peak

    # Presence inside the jet region, scanning forward from the peak.
    end_scan = min(n, peak + scan_cap)
    presence = np.empty(end_scan - peak, dtype=np.float64)
    for k, i in enumerate(range(peak, end_scan)):
        diff = np.abs(frame_getter(i) - bg)
        presence[k] = np.count_nonzero((diff > PRESENCE_DIFF) & mask)

    if presence.size < 5:
        return start, peak, peak

    # The jet decays from the onset peak to a trough (jet gone), after which
    # slow scene drift can push presence back up. So find the *first* sustained
    # low region after the peak -- that is where the jet ends -- using a floor
    # taken from the smoothed trough (drift-immune, since drift sits higher).
    smooth = _moving_average(presence, END_SMOOTH_WIN)
    floor = float(smooth.min())
    low_threshold = max(2.0, residual_k * floor)
    is_low = smooth <= low_threshold

    end = None
    for k in range(END_MIN_GAP, presence.size):
        run_end = min(presence.size, k + END_HOLD)
        if is_low[k] and is_low[k:run_end].all():
            end = peak + k
            break
    if end is None:
        end = peak + int(np.argmin(smooth))
    return start, max(end, peak), peak


def make_dest_dir(source_dir, dest_base):
    """Build a unique destination folder named after the source run.

    Run stamps are second-resolution, so a counter suffix (not another
    timestamp, which collides with itself inside one second) keeps re-runs
    and back-to-back monitor events apart.
    """
    source_dir = Path(source_dir)
    dest_base = Path(dest_base)
    candidate = dest_base / source_dir.name
    n = 2
    while candidate.exists():
        candidate = dest_base / f"{source_dir.name}_{n}"
        n += 1
    return candidate


def extract_injection(
    source_dir,
    dest_base=None,
    before=30,
    after=30,
    diff_thresh=25,
    frac=0.005,
    abs_floor=30.0,
    gap=5,
    min_peak=300.0,
    copy=True,
    progress=None,
    end_rule="presence",
):
    """Detect the injection in *source_dir* and copy the padded window out.

    Returns a result dict with the detection metadata and copied file list.
    Raises ``RuntimeError`` if no frames or no injection are found.

    ``end_rule`` is passed to :func:`detect_bounds_with_presence`; use
    ``"temporal"`` for a scene that stays changed after the event (gel).
    """
    source_dir = Path(source_dir)
    files = list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")

    signal, method = compute_motion_signal_best(
        files, diff_thresh=diff_thresh, progress=progress
    )

    getter = raw_downsample_getter(files)
    if getter is not None:
        bounds = detect_bounds_with_presence(
            signal, getter, len(files),
            frac=frac, abs_floor=abs_floor, gap=gap, min_peak=min_peak,
            end_rule=end_rule,
        )
    else:
        bounds = detect_injection_bounds(
            signal, frac=frac, abs_floor=abs_floor, gap=gap, min_peak=min_peak
        )
    if bounds is None:
        raise RuntimeError(
            "No injection detected. The motion in this burst is too small "
            "(no clear high-pressure jet event)."
        )

    start, end, peak = bounds
    return build_result(
        files, signal, method, start, end, peak,
        source_dir, dest_base, before, after, copy,
    )


def build_result(
    files, signal, method, start, end, peak,
    source_dir, dest_base, before, after, copy,
):
    """Copy the [start-before .. end+after] window and return the metadata dict.

    Detection (start/end/peak) is already done; this only copies files, so it
    reads nothing back -- ideal for the in-memory after-capture path.
    """
    files = [Path(f) for f in files]
    signal = np.asarray(signal, dtype=np.float64)
    copy_start = max(0, start - before)
    copy_end = min(len(files) - 1, end + after)
    selected = files[copy_start : copy_end + 1]

    if dest_base is None:
        dest_base = Path(source_dir).parents[0] / DEST_FOLDER_NAME
    dest_dir = make_dest_dir(source_dir, dest_base)

    if copy:
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src in selected:
            shutil.copy2(src, dest_dir / src.name)
        # Record where the jet-free head ends so measure_angle can build a
        # pre-onset background (BG_MODE="pre-onset") without the jet in it.
        meta = {
            "pre_frames": int(start - copy_start),
            "onset_index": int(start),
            "copy_start": int(copy_start),
            "copy_end": int(copy_end),
            "method": str(method),
        }
        try:
            (dest_dir / "injection_meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8")
        except OSError:
            pass    # metadata is an optimization, never a failure

    return {
        "source_dir": str(source_dir),
        "dest_dir": str(dest_dir),
        "method": method,
        "total_frames": len(files),
        "peak_index": peak,
        "peak_frame": files[peak].name,
        "peak_value": int(signal[peak]),
        "injection_start_frame": files[start].name,
        "injection_end_frame": files[end].name,
        "injection_count": end - start + 1,
        "copy_start_frame": files[copy_start].name,
        "copy_end_frame": files[copy_end].name,
        "selected_count": len(selected),
        "before": before,
        "after": after,
        "copied": copy,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="folder of burst frames to analyze")
    parser.add_argument("--dest", default=None, help="destination base folder")
    parser.add_argument("--before", type=int, default=30, help="frames to keep before injection start")
    parser.add_argument("--after", type=int, default=30, help="frames to keep after injection end")
    parser.add_argument("--diff-thresh", type=int, default=25, help="per-pixel change threshold")
    parser.add_argument("--frac", type=float, default=0.005, help="active threshold as fraction of peak")
    parser.add_argument("--dry-run", action="store_true", help="detect only, do not copy")
    args = parser.parse_args()

    def progress(done, total):
        print(f"\rAnalyzing {done}/{total}", end="", flush=True)

    result = extract_injection(
        args.source,
        dest_base=args.dest,
        before=args.before,
        after=args.after,
        diff_thresh=args.diff_thresh,
        frac=args.frac,
        copy=not args.dry_run,
        progress=progress,
    )
    print()
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
