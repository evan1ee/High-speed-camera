#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Measure the piston's stroke, speed and travel curves from an injection folder.

For every frame: fit the green line to the piston's left edge
(:mod:`hsc.piston_track`), measure the perpendicular distance from that line to
the line in the **stroke-start frame**, convert px to mm with the stored scale
calibration, and differentiate against the frame time base to get speed.

Outputs, all inside ``data\\measure\\<run>\\``:

* one annotated image per frame (native capture size, green edge line),
* ``piston_speed.csv`` -- per-frame distance/speed plus a summary block,
* ``distance_time.png`` / ``speed_time.png`` -- the two curves.

Time base
---------
Frame indices are not time: the camera free-runs, and a frame can be dropped.
``Capture Piston`` therefore records each frame's SDK timestamp into
``piston_meta.json``; :func:`resolve_timebase` uses those, but only after they
agree with the burst's measured frame rate -- the SDK's tick unit is not
documented, so the unit is *inferred* (us / ns / ms) rather than assumed, and
timestamps that agree with nothing are discarded in favour of the plain frame
rate. No camera or SDK is needed here, so this runs headless on saved frames.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.signal import savgol_filter

from hsc import calibrate_scale
from hsc import injection_extract
from hsc import piston_plot
from hsc import piston_track


DEST_FOLDER_NAME = "measure"
CSV_NAME = "piston_speed.csv"
DISTANCE_PLOT = "distance_time.png"
SPEED_PLOT = "speed_time.png"

SMOOTH_WINDOW = 15         # Savitzky-Golay window for the speed derivative
SMOOTH_POLY = 2
UNIFORM_DT_TOL = 0.2       # relative dt spread still counted as evenly spaced
TIMEBASE_TOL = 0.05        # timestamps must imply the measured FPS this closely
#: Candidate units of the SDK's frame timeStamp, as a factor to microseconds.
TIMESTAMP_UNITS = (("us", 1.0), ("ns", 1e-3), ("ms", 1e3))

PISTON_RENDER_SCALE = 1    # saved frames keep the capture size (320x240)
PISTON_LINE_SS = 2         # draw supersampled, then area-downscale: thin lines
LINE_COLOR = (0, 255, 0)   # BGR -> green
TEXT_COLOR = (0, 255, 0)


# ---- Time base -----------------------------------------------------------
def resolve_timebase(meta, n, fps=None):
    """Return ``(times_s, source, fps)`` for *n* frames.

    ``times_s`` starts at 0 on the first frame of the folder. *fps* (the
    operator's fallback) wins over the value stored in the meta when both are
    present. Raises if there is no usable timing at all -- a speed curve
    invented from an assumed frame rate would look perfectly plausible and be
    silently wrong.
    """
    meta = meta or {}
    meta_fps = _positive(meta.get("fps"))
    ref_fps = _positive(fps) or meta_fps

    stamps = meta.get("frame_times_us")
    if stamps is not None and len(stamps) == n and n >= 2:
        raw = np.asarray(stamps, dtype=float)
        if np.all(np.diff(raw) >= 0) and raw[-1] > raw[0]:
            best = None
            for name, factor in TIMESTAMP_UNITS:
                seconds = (raw - raw[0]) * factor / 1e6
                implied = (n - 1) / seconds[-1]
                if ref_fps is None:
                    best = (0.0, "us (unverified)", seconds, implied)
                    break
                error = abs(implied - ref_fps) / ref_fps
                if error <= TIMEBASE_TOL and (best is None or error < best[0]):
                    best = (error, name, seconds, implied)
            if best is not None:
                _err, name, seconds, implied = best
                return seconds, f"timestamps ({name})", float(implied)

    if ref_fps:
        return np.arange(n, dtype=float) / ref_fps, "fps", float(ref_fps)
    raise RuntimeError(
        "No frame timing for this folder: it has no piston_meta.json and no "
        "frame rate was given. Measure a folder made by Capture Piston, or "
        "enter the capture FPS.")


def _positive(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _speed(distance, times):
    """Derivative of *distance* w.r.t. *times*, per second.

    Computed over the whole series in one pass. The reported peak is the
    maximum of exactly this column, so the plotted curve and the summary can
    never disagree -- they are the same numbers.

    Uses the Savitzky-Golay least-squares derivative on evenly spaced frames
    (far quieter than differencing a smoothed series); falls back to a central
    difference when the timestamps are not evenly spaced.
    """
    distance = np.asarray(distance, dtype=float)
    times = np.asarray(times, dtype=float)
    n = distance.size
    if n < 3:
        return np.full(n, np.nan)

    filled = piston_track._filled(distance)
    if filled is None:
        return np.full(n, np.nan)

    steps = np.diff(times)
    dt = float(np.median(steps))
    even = dt > 0 and float(np.max(np.abs(steps - dt))) <= UNIFORM_DT_TOL * dt

    window = min(SMOOTH_WINDOW, n if n % 2 else n - 1)
    if window % 2 == 0:
        window -= 1
    if even and window > SMOOTH_POLY + 1:
        return savgol_filter(filled, window, SMOOTH_POLY, deriv=1, delta=dt)
    if window > SMOOTH_POLY + 1:
        filled = savgol_filter(filled, window, SMOOTH_POLY)
    return np.gradient(filled, times)


# ---- Annotation ----------------------------------------------------------
def annotate(gray, fit, profile, label="", scale=PISTON_LINE_SS):
    """Draw the fitted green edge line (and a label) on a frame.

    The line is extended across the FULL image height, not just the band it
    was fitted from: the band is where the edge can be measured reliably, but
    a full-height line is what makes the position -- and the fact that every
    frame's line is parallel -- readable at a glance.
    """
    big = cv2.resize(gray, (gray.shape[1] * scale, gray.shape[0] * scale),
                     interpolation=cv2.INTER_CUBIC)
    img = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
    if fit is not None:
        y0, y1 = 0, gray.shape[0] - 1
        p0 = (int(round((fit["k"] * y0 + fit["b"]) * scale)), int(round(y0 * scale)))
        p1 = (int(round((fit["k"] * y1 + fit["b"]) * scale)), int(round(y1 * scale)))
        cv2.line(img, p0, p1, LINE_COLOR, 1, cv2.LINE_AA)
    if label:
        cv2.putText(img, label, (4 * scale, 12 * scale), cv2.FONT_HERSHEY_SIMPLEX,
                    0.32 * scale, TEXT_COLOR, 1, cv2.LINE_AA)
    return img


def _mm_per_px(mm_per_px, frame_shape, warn=None):
    """Resolve the scale: explicit argument, else the stored calibration."""
    if mm_per_px is not None:
        return float(mm_per_px), "explicit"
    cal = calibrate_scale.load_calibration()
    if not cal or not _positive(cal.get("mm_per_px")):
        if warn:
            warn("No scale calibration found -- distances are reported in "
                 "pixels only (run Calibrate Scale to get mm).")
        return 0.0, "none"
    size = cal.get("image_size")
    height, width = frame_shape[:2]
    if size and list(size) != [width, height]:
        if warn:
            warn(f"Calibration was made on {size[0]}x{size[1]} frames but "
                 f"these are {width}x{height}: the mm values assume the same "
                 "magnification. Re-run Calibrate Scale on the piston view if "
                 "the zoom differs.")
    return float(cal["mm_per_px"]), "calibration.json"


def _load_meta(source_dir):
    for name in (piston_track.META_NAME, "injection_meta.json"):
        path = Path(source_dir) / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


# ---- Main entry point ----------------------------------------------------
def measure_folder(source_dir, dest_base=None, fps=None, mm_per_px=None,
                   progress=None, log=None):
    """Measure every frame of *source_dir* and write images, CSV and curves."""
    source_dir = Path(source_dir)
    files = injection_extract.list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")

    warnings = []

    def warn(message):
        warnings.append(message)
        if log is not None:
            log(message)

    meta = _load_meta(source_dir)
    times, timebase, fps_used = resolve_timebase(meta, len(files), fps)

    # Every frame here belongs to the stroke, so this is where the band can be
    # narrowed to the piston's flat face (see piston_track.refine_band).
    profile = piston_track.refine_band(
        files, piston_track.build_profile(files))
    tracked = piston_track.track(files, profile=profile, progress=progress)
    fits = tracked["fits"]

    # One slope for the whole run, so every drawn line is exactly parallel and
    # consecutive frames differ by the pure translation the piston performs.
    slope = piston_track.common_slope(fits)
    if slope is not None:
        piston_track.apply_common_slope(fits, slope, profile)
        for i, fit in enumerate(fits):
            if fit is not None:
                tracked["x"][i] = fit["x"]

    first_gray = piston_track._as_gray(files[0])
    scale_mm, scale_source = _mm_per_px(mm_per_px, first_gray.shape, warn)

    ref_index = _reference_index(tracked, meta, fits)
    if ref_index is None:
        raise RuntimeError(
            "The piston edge was not found in any frame -- check the barrel is "
            "lit and in view.")
    ref_fit = fits[ref_index]

    distance_px = np.array(
        [piston_track.line_distance(ref_fit, fit, profile) for fit in fits])
    distance_mm = (distance_px * scale_mm if scale_mm > 0
                   else np.full(distance_px.shape, np.nan))
    times_rel = times - times[ref_index]

    # Frames whose position step is beyond what the piston can do are REPORTED
    # (the CSV's `stable` column, and the warning below) but never suppressed:
    # the peak is the plain maximum of the speed column, so what the operator
    # reads off the curve is what the summary states.
    unstable = piston_track.implausible_steps(tracked["x"])

    curve = distance_mm if scale_mm > 0 else distance_px
    speed = _speed(curve, times_rel)                   # mm/s (or px/s)
    speed_mm_s = speed if scale_mm > 0 else np.full(speed.shape, np.nan)

    missing = int(np.count_nonzero(~np.isfinite(distance_px)))
    if missing:
        warn(f"{missing} of {len(files)} frames have no detectable piston edge "
             "(blank rows in the CSV).")
    border = [files[i].name for i, fit in enumerate(fits)
              if fit is not None and fit["at_border"]]
    if border:
        warn(f"The piston edge reaches the frame border in {len(border)} "
             "frame(s): the stroke may continue out of view.")

    bounds = piston_track.detect_piston_bounds(tracked["x"])
    if bounds is None:
        warn("No clear stroke in this folder: the summary covers every frame.")
        move_start, move_end = 0, len(files) - 1
    else:
        move_start, move_end = bounds

    # Travel at the END of the stroke, not the largest value anywhere in the
    # folder: the padding after the stroke can contain the piston leaving the
    # view, where the tracked position jumps around and a global max would
    # report one of those spikes as the stroke.
    smoothed = piston_track._filled(distance_px)
    if smoothed is not None:
        smoothed = piston_track._median_filter(smoothed)
        stroke_px = float(smoothed[move_end])
    else:
        stroke_px = float("nan")
    stroke_mm = stroke_px * scale_mm if scale_mm > 0 else float("nan")
    duration_ms = float((times_rel[move_end] - times_rel[move_start]) * 1000.0)
    mean_speed = (stroke_mm / (duration_ms / 1000.0)
                  if scale_mm > 0 and duration_ms > 0 else float("nan"))
    if unstable.any():
        bad_times = times_rel[unstable] * 1000.0
        warn(f"{int(unstable.sum())} frame(s) at "
             f"{', '.join(f'{t:.0f}' for t in bad_times[:6])} ms step further "
             f"than {piston_track.MAX_STEP_PX:.0f} px between frames. They are "
             "marked in the CSV's `stable` column; the speed they produce is "
             "still reported.")

    # The peak is the maximum of the speed column, full stop.
    finite = np.isfinite(speed_mm_s)
    peak_speed = (float(np.max(speed_mm_s[finite]))
                  if scale_mm > 0 and finite.any() else float("nan"))

    if dest_base is None:
        parents = source_dir.parents
        base = parents[1] if len(parents) > 1 else source_dir.parent
        dest_base = base / DEST_FOLDER_NAME
    dest_dir = injection_extract.make_dest_dir(source_dir, dest_base)
    dest_dir.mkdir(parents=True, exist_ok=True)

    for i, path in enumerate(files):
        gray = piston_track._as_gray(path)
        if scale_mm > 0 and np.isfinite(distance_mm[i]):
            label = f"{distance_mm[i]:+.2f}mm {speed_mm_s[i]:.0f}mm/s"
        elif np.isfinite(distance_px[i]):
            label = f"{distance_px[i]:+.1f}px"
        else:
            label = "no edge"
        image = annotate(gray, fits[i], profile, label)
        if PISTON_LINE_SS != 1:
            image = cv2.resize(
                image,
                (gray.shape[1] * PISTON_RENDER_SCALE,
                 gray.shape[0] * PISTON_RENDER_SCALE),
                interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(dest_dir / path.name), image)

    _write_csv(dest_dir / CSV_NAME, files, times_rel, tracked["x"], distance_px,
               distance_mm, speed_mm_s, fits, unstable,
               summary={
                   "unstable_frames": int(unstable.sum()),
                   "stroke_px": stroke_px,
                   "stroke_mm": stroke_mm,
                   "duration_ms": duration_ms,
                   "mean_speed_mm_s": mean_speed,
                   "peak_speed_mm_s": peak_speed,
                   "mm_per_px": scale_mm,
                   "scale_source": scale_source,
                   "fps": fps_used,
                   "timebase": timebase,
                   "reference_frame": files[ref_index].name,
                   "stroke_frames": f"{files[move_start].name}"
                                    f"..{files[move_end].name}",
               })

    time_ms = times_rel * 1000.0
    piston_plot.save_line_plot(
        dest_dir / DISTANCE_PLOT, time_ms, curve,
        title=f"Piston travel - {source_dir.name}", x_label="time (ms)",
        y_label="distance (mm)" if scale_mm > 0 else "distance (px)", mark_x=0.0)
    piston_plot.save_line_plot(
        dest_dir / SPEED_PLOT, time_ms, speed,
        title=f"Piston speed - {source_dir.name}", x_label="time (ms)",
        y_label="speed (mm/s)" if scale_mm > 0 else "speed (px/s)", mark_x=0.0)

    return {
        "source_dir": str(source_dir),
        "dest_dir": str(dest_dir),
        "csv_path": str(dest_dir / CSV_NAME),
        "measured_count": len(files),
        "missing_count": missing,
        "border_count": len(border),
        "reference_frame": files[ref_index].name,
        "reference_index": int(ref_index),
        "stroke_px": stroke_px,
        "stroke_mm": stroke_mm,
        "duration_ms": duration_ms,
        "mean_speed_mm_s": mean_speed,
        "peak_speed_mm_s": peak_speed,
        "mm_per_px": scale_mm,
        "scale_source": scale_source,
        "fps": fps_used,
        "timebase": timebase,
        "move_start_frame": files[move_start].name,
        "move_end_frame": files[move_end].name,
        "band": profile.as_dict(),
        "warnings": warnings,
    }


def _reference_index(tracked, meta, fits):
    """Index of the stroke-start frame every distance is measured against."""
    bounds = piston_track.detect_piston_bounds(tracked["x"])
    candidates = []
    if bounds is not None:
        candidates.append(bounds[0])
    pre = meta.get("pre_frames")
    if isinstance(pre, int) and 0 <= pre < len(fits):
        candidates.append(pre)
    candidates.extend(i for i, fit in enumerate(fits) if fit is not None)
    for index in candidates:
        if 0 <= index < len(fits) and fits[index] is not None:
            return int(index)
    return None


def _write_csv(path, files, times_rel, xs, distance_px, distance_mm,
               speed_mm_s, fits, unstable, summary):
    def num(value, fmt):
        return format(value, fmt) if np.isfinite(value) else ""

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("frame,time_ms,x_px,distance_px,distance_mm,speed_mm_s,"
                 "speed_m_s,k,n_points,rms_px,coverage,at_border,stable\n")
        for i, file in enumerate(files):
            fit = fits[i]
            fh.write(
                f"{file.name},{times_rel[i] * 1000.0:.3f},"
                f"{num(xs[i], '.3f')},{num(distance_px[i], '.3f')},"
                f"{num(distance_mm[i], '.4f')},{num(speed_mm_s[i], '.2f')},"
                f"{num(speed_mm_s[i] / 1000.0, '.4f')},"
                f"{num(fit['k'], '.5f') if fit else ''},"
                f"{fit['n_points'] if fit else ''},"
                f"{num(fit['rms'], '.3f') if fit else ''},"
                f"{num(fit['coverage'], '.3f') if fit else ''},"
                f"{('yes' if fit['at_border'] else 'no') if fit else ''},"
                f"{'no' if unstable[i] else 'yes'}\n")
        fh.write("\n")
        for key, value in summary.items():
            if isinstance(value, float):
                value = format(value, ".4f") if np.isfinite(value) else "n/a"
            fh.write(f"{key},{value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="an injection-images folder of piston frames")
    parser.add_argument("--dest", default=None, help="destination base folder")
    parser.add_argument("--fps", type=float, default=None,
                        help="capture frame rate, if the folder has no meta")
    parser.add_argument("--mm-per-px", type=float, default=None,
                        help="override the stored scale calibration")
    args = parser.parse_args()

    def progress(done, total):
        print(f"\rMeasuring {done}/{total}", end="", flush=True)

    result = measure_folder(args.source, dest_base=args.dest, fps=args.fps,
                            mm_per_px=args.mm_per_px, progress=progress,
                            log=lambda m: print(f"\n[warn] {m}"))
    print()
    for key in ("stroke_mm", "duration_ms", "mean_speed_mm_s",
                "peak_speed_mm_s", "fps", "timebase", "dest_dir"):
        print(f"{key}: {result[key]}")


if __name__ == "__main__":
    main()
