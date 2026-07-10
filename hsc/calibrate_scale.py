#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Spatial calibration: mm per pixel from two reference edges a known distance apart.

Industrial-style ROI workflow: the user draws a Region Of Interest around each
of the two reference edges of a gauge block. The block may image either as a
**bright bar on a dark background** (its two reference edges are the bright<->dark
*steps* at the block boundary) or as a bright block with **dark chamfer edge-lines**
(the true edge is the outer flank of each dark line). Detection auto-selects the
polarity, so the same workflow serves both. Inside each ROI the software finds the
edge automatically to sub-pixel precision and fits a straight line to it; the
perpendicular distance between the two fitted lines is the reference length in
pixels:

    ROI -> Gaussian blur -> per-scanline edge (sub-pixel) -> TLS line fit
    mm_per_px = ref_mm / perpendicular_distance_px

The ROI removes reflections, the nozzle and other background clutter that defeat
whole-frame auto-detection; the user only indicates *where* each edge is, the
software locates it precisely. Results (mm/px, the two line params) are stored in
``calibration.json`` via ``settings_path``; an annotated ``*_scale.bmp`` shows the
two green lines + the value. Interactive use is via the GUI "Calibrate Scale"
button (see ``calibrate_ui.py``). CLI, for scripting/tests:

    python calibrate_scale.py still.bmp --ref-mm 10 \\
        --roi1 5 30 130 62  --roi2 5 185 130 220

Each ROI is ``x0 y0 x1 y1`` in image pixels. The scale stays valid while the
lens, zoom and working distance are unchanged (the ROI/aspect preset does not
affect it -- cropping changes the field of view, not the pixel size).
"""

import argparse
import json
import os
import shutil
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d

from hsc import measure_angle as ma
from hsc.app_paths import data_root, settings_path


CALIBRATION_FILE = "calibration.json"
SCALE_STILL_DIR = data_root() / "measure" / "block"
EDGE_SMOOTH = 1.0          # sub-pixel smoothing along each scan line
EDGE_FEATURE = "dark"      # "dark" line (min), "bright" line (max), or "step" (grad)
MIN_EDGE_POINTS = 8


def _clip_roi(roi, w, h):
    x0, y0, x1, y1 = (int(round(v)) for v in roi)
    x0, x1 = sorted((max(0, x0), min(w, x1)))
    y0, y1 = sorted((max(0, y0), min(h, y1)))
    if x1 - x0 < 3 or y1 - y0 < 3:
        raise RuntimeError("ROI is too small - draw a larger box around the edge.")
    return x0, y0, x1, y1


def _scanline_edge(values, feature):
    """Sub-pixel position of the edge within one scan line (0-based index)."""
    if feature == "bright":
        k = int(np.argmax(values))
        return k + ma._parabolic_vertex_offset(values, k)
    if feature == "step":
        grad = np.abs(np.gradient(values))
        k = int(np.argmax(grad))
        return k + ma._parabolic_vertex_offset(grad, k)
    k = int(np.argmin(values))          # "dark" line (default)
    return k + ma._parabolic_vertex_offset(values, k)


def _scanline_outer_edge(values, outer_sign):
    """Sub-pixel outer boundary of a dark line within one scan line.

    A chamfered block edge shows up as a dark line (the chamfer reflects light
    away); the true block edge is the *outer* flank of that line, not its centre.
    From the dark minimum we take the steepest-gradient point on the flank facing
    outward (``outer_sign`` = -1 toward index 0, +1 toward the high index):
    the falling bright->dark transition for the outer side, or the rising
    dark->bright transition, whichever is outward.
    """
    m = int(np.argmin(values))          # dark-line centre
    grad = np.gradient(values)
    if outer_sign < 0:                  # outer flank is above the centre (falling)
        if m < 1:
            return float(m)
        k = int(np.argmin(grad[: m + 1]))          # steepest fall
    else:                               # outer flank is below the centre (rising)
        if m > len(values) - 2:
            return float(m)
        k = m + int(np.argmax(grad[m:]))           # steepest rise
    return k + ma._parabolic_vertex_offset(grad, k)


def detect_edge_in_roi(gray, roi, feature=EDGE_FEATURE, blur=EDGE_SMOOTH,
                       outer_sign=None):
    """Find the edge inside ``roi`` and fit a line to it (sub-pixel, TLS).

    Orientation follows the ROI's shape: a wide, short ROI -> horizontal edge
    (scanned column-by-column, ``y = k*x + b``); a tall, narrow ROI -> vertical
    edge (scanned row-by-row, ``x = k*y + b``). With ``outer_sign`` set, the
    *outer boundary* of a dark chamfer line is located (see
    ``_scanline_outer_edge``); otherwise the ``feature`` extremum (dark centre by
    default). Returns a dict with the line params, orientation, sub-pixel points
    and the clipped ROI.
    """
    gray = gray.astype(np.float64)
    h, w = gray.shape
    x0, y0, x1, y1 = _clip_roi(roi, w, h)
    sub = gray[y0:y1, x0:x1]
    horizontal = (x1 - x0) >= (y1 - y0)

    def locate(line):
        if outer_sign is not None:
            return _scanline_outer_edge(line, outer_sign)
        return _scanline_edge(line, feature)

    pts = []
    if horizontal:
        s = gaussian_filter1d(sub, blur, axis=0)     # smooth down each column
        for c in range(s.shape[1]):
            pts.append((x0 + c, y0 + locate(s[:, c])))
    else:
        s = gaussian_filter1d(sub, blur, axis=1)     # smooth across each row
        for r in range(s.shape[0]):
            pts.append((x0 + locate(s[r, :]), y0 + r))
    pts = np.array(pts, dtype=float)
    if len(pts) < MIN_EDGE_POINTS:
        raise RuntimeError("Not enough edge samples in the ROI to fit a line.")

    if horizontal:
        k, b, _, _, _ = ma.tls_fit(pts[:, 0], pts[:, 1])   # y = k*x + b
    else:
        k, b, _, _, _ = ma.tls_fit(pts[:, 1], pts[:, 0])   # x = k*y + b
    return {"horizontal": horizontal, "k": float(k), "b": float(b),
            "points": pts, "roi": (x0, y0, x1, y1)}


def _line_gap(edge_a, edge_b):
    """Symmetric median perpendicular distance (px) between two fitted lines."""
    def perp(pts, e):
        if e["horizontal"]:
            resid = pts[:, 1] - (e["k"] * pts[:, 0] + e["b"])
        else:
            resid = pts[:, 0] - (e["k"] * pts[:, 1] + e["b"])
        return float(np.median(np.abs(resid)) / np.hypot(1.0, e["k"]))
    return 0.5 * (perp(edge_b["points"], edge_a) + perp(edge_a["points"], edge_b))


def _roi_is_dark_line(gray, roi, w, h):
    """True if ``roi`` straddles a DARK edge-line (a dark trough with brighter
    pixels on BOTH sides), as opposed to a bright<->dark step at a block edge.

    Collapses the ROI along its edge-parallel axis to a 1-D profile across the
    scan axis and checks whether the darkest sample sits in the interior with
    both ends clearly brighter (dark line) or at an end (a step).
    """
    x0, y0, x1, y1 = _clip_roi(roi, w, h)
    sub = gray[y0:y1, x0:x1].astype(np.float64)
    horizontal = (x1 - x0) >= (y1 - y0)
    prof = np.median(sub, axis=1) if horizontal else np.median(sub, axis=0)
    k = int(np.argmin(prof))
    if k <= 0 or k >= len(prof) - 1:
        return False                       # darkest at an end -> a step, not a line
    return (prof[0] - prof[k] >= 0.3 * DARK_MIN_DEPTH
            and prof[-1] - prof[k] >= 0.3 * DARK_MIN_DEPTH
            and max(prof[0], prof[-1]) - prof[k] >= DARK_MIN_DEPTH)


def _auto_fit_mode(gray, roi1, roi2, w, h):
    """Pick the edge locus from the ROI content: ``"outer"`` (dark chamfer line)
    only when BOTH ROIs look like dark lines, else ``"step"`` (bright block edge --
    the polarity-agnostic gradient peak that suits the bright 5 mm block)."""
    dark = sum(_roi_is_dark_line(gray, roi, w, h) for roi in (roi1, roi2))
    return "outer" if dark == 2 else "step"


def calibrate_from_rois(gray, roi1, roi2, ref_mm, mode="auto"):
    """Detect both edges, measure their gap, and return a calibration record.

    ``mode="auto"`` (default) inspects the ROIs and uses ``"step"`` for a bright
    block edge or ``"outer"`` for a dark chamfer edge-line. ``mode="outer"``
    locates the OUTER boundary of each dark chamfer line -- the real block edge --
    with each ROI's outer side taken as the side facing away from the other ROI.
    ``mode`` "dark"/"bright"/"step" instead uses that ``feature`` extremum
    directly (dark-line centre, bright peak, or gradient peak/step).
    """
    h, w = gray.shape
    if mode == "auto":
        mode = _auto_fit_mode(gray, roi1, roi2, w, h)
    if mode == "outer":
        c1 = _clip_roi(roi1, w, h)
        c2 = _clip_roi(roi2, w, h)
        horizontal = (c1[2] - c1[0]) >= (c1[3] - c1[1])
        # Separation axis: y for horizontal edges, x for vertical edges.
        ax = 1 if horizontal else 0
        mid1 = 0.5 * (c1[ax] + c1[ax + 2])
        mid2 = 0.5 * (c2[ax] + c2[ax + 2])
        sign1 = -1 if mid1 <= mid2 else 1          # outward = away from the other ROI
        e1 = detect_edge_in_roi(gray, roi1, outer_sign=sign1)
        e2 = detect_edge_in_roi(gray, roi2, outer_sign=-sign1)
    else:
        e1 = detect_edge_in_roi(gray, roi1, feature=mode)
        e2 = detect_edge_in_roi(gray, roi2, feature=mode)
    gap = _line_gap(e1, e2)
    if gap <= 0:
        raise RuntimeError("The two ROIs resolved to the same line (zero gap).")
    mm_per_px = float(ref_mm) / gap
    return {
        "mm_per_px": mm_per_px,
        "px_per_mm": 1.0 / mm_per_px,
        "ref_mm": float(ref_mm),
        "gap_px": gap,
        "edge1": e1,
        "edge2": e2,
    }


def _line_endpoints(edge, w, h):
    k, b = edge["k"], edge["b"]
    x0, y0, x1, y1 = edge["roi"]
    if edge["horizontal"]:               # draw across the ROI's x-span
        return (x0, k * x0 + b), (x1, k * x1 + b)
    return (k * y0 + b, y0), (k * y1 + b, y1)


def annotate(gray, result, scale=3, text_lines=None):
    """Two green fitted lines + the ROI boxes + gap connector + value text."""
    big = cv2.resize(gray, (gray.shape[1] * scale, gray.shape[0] * scale),
                     interpolation=cv2.INTER_CUBIC)
    img = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
    h, w = gray.shape
    for e in (result["edge1"], result["edge2"]):
        x0, y0, x1, y1 = [v * scale for v in e["roi"]]
        cv2.rectangle(img, (x0, y0), (x1, y1), (0, 160, 255), 1)
        a, c = _line_endpoints(e, w, h)
        # extend the fitted line across the full frame for a clear reference
        if e["horizontal"]:
            a = (0, e["k"] * 0 + e["b"]); c = (w - 1, e["k"] * (w - 1) + e["b"])
        else:
            a = (e["k"] * 0 + e["b"], 0); c = (e["k"] * (h - 1) + e["b"], h - 1)
        p0 = tuple(np.round(np.array(a) * scale).astype(int))
        p1 = tuple(np.round(np.array(c) * scale).astype(int))
        cv2.line(img, p0, p1, (0, 255, 0), 1, cv2.LINE_AA)

    # Gap connector at the shared centre.
    e1, e2 = result["edge1"], result["edge2"]
    if e1["horizontal"]:
        xm = (e1["roi"][0] + e1["roi"][2]) / 2.0
        a = (xm, e1["k"] * xm + e1["b"]); c = (xm, e2["k"] * xm + e2["b"])
    else:
        ym = (e1["roi"][1] + e1["roi"][3]) / 2.0
        a = (e1["k"] * ym + e1["b"], ym); c = (e2["k"] * ym + e2["b"], ym)
    ca = tuple(np.round(np.array(a) * scale).astype(int))
    cc = tuple(np.round(np.array(c) * scale).astype(int))
    cv2.arrowedLine(img, ca, cc, (0, 200, 255), 1, cv2.LINE_AA, tipLength=0.03)
    cv2.arrowedLine(img, cc, ca, (0, 200, 255), 1, cv2.LINE_AA, tipLength=0.03)

    if text_lines is None:
        text_lines = [
            f"{result['ref_mm']:g} mm = {result['gap_px']:.1f} px",
            f"{result['mm_per_px']:.5f} mm/px  ({result['px_per_mm']:.2f} px/mm)",
        ]
    for i, line in enumerate(text_lines):
        cv2.putText(img, line, (6 * scale, (16 + 14 * i) * scale),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4 * scale, (0, 255, 0), 1, cv2.LINE_AA)
    return img


def _atomic_write_json(path, record):
    """Write *record* as JSON to *path*, backing up any existing file first.

    Keeps a ``<name>.bak`` copy of the previous version and writes via a temp
    file + ``os.replace`` so a crash mid-write can't leave a truncated file.
    """
    path = Path(path)
    if path.exists():
        try:
            # copy (not copy2): the .bak's mtime = when the backup was made,
            # matching the new file's save time instead of the old version's.
            shutil.copy(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save_calibration(result, image_path, save_json=True):
    """Write the annotated check image and (optionally) calibration.json."""
    image_path = Path(image_path)
    gray = ma.load_gray(image_path)
    out_img = annotate(gray, result)
    out_path = image_path.with_name(image_path.stem + "_scale.bmp")
    cv2.imwrite(str(out_path), out_img)

    record = {
        "mm_per_px": result["mm_per_px"],
        "px_per_mm": result["px_per_mm"],
        "ref_mm": result["ref_mm"],
        "gap_px": result["gap_px"],
        "edge1": [result["edge1"]["k"], result["edge1"]["b"], result["edge1"]["roi"]],
        "edge2": [result["edge2"]["k"], result["edge2"]["b"], result["edge2"]["roi"]],
        "image": str(image_path),
        "image_size": [int(gray.shape[1]), int(gray.shape[0])],
        "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "annotated": str(out_path),
    }
    if save_json:
        cal_path = settings_path(CALIBRATION_FILE)
        _atomic_write_json(cal_path, record)
        record["calibration_file"] = str(cal_path)
    return record


def calibrate(image_path, roi1, roi2, ref_mm, mode="auto", save=True):
    """One-shot: detect edges in the two ROIs and store the calibration."""
    gray = ma.load_gray(Path(image_path))
    result = calibrate_from_rois(gray, roi1, roi2, ref_mm, mode)
    return save_calibration(result, image_path, save_json=save)


DARK_MIN_DEPTH = 35        # a column trough must dip this many gray levels below
                           # its own bright level to count as a dark edge line
BRIGHT_MIN_RISE = 35       # the block interior must exceed the background by this
                           # many gray levels for a column to count (bright block)
AUTO_MIN_SEP_FRAC = 0.20   # the two edges must span >= this fraction of the region
AUTO_MIN_COL_FRAC = 0.25   # this fraction of scan lines must show BOTH edges


def _two_edges_bright(region):
    """Per-scanline detection of the two parallel edges of a BRIGHT block.

    The 5 mm calibration block images as a bright bar on a dark background, so
    its two reference edges are the outer boundaries of the block's bright run
    (bright<->dark steps), not dark lines. For each scan line keep the longest
    bright run above that line's own mid-level (robust to uneven lighting); its
    first and last positions are the near/far edges, required well separated.
    Longest-run selection ignores small reflections and every scan line votes,
    so a tilted or locally-faint block still resolves. Returns
    ``(pos_near, pos_far, n_support)`` or None.
    """
    h, wr = region.shape
    near, far = [], []
    for x in range(wr):
        col = gaussian_filter1d(region[:, x].astype(np.float64), EDGE_SMOOTH)
        lo = float(np.percentile(col, 10))
        hi = float(np.percentile(col, 90))
        if hi - lo < BRIGHT_MIN_RISE:                  # no clear block here
            continue
        bright = np.flatnonzero(col > 0.5 * (lo + hi))
        if bright.size < 2:
            continue
        runs = np.split(bright, np.flatnonzero(np.diff(bright) > 1) + 1)
        run = max(runs, key=len)
        a, b = int(run[0]), int(run[-1])
        if b - a >= AUTO_MIN_SEP_FRAC * h and a > 0 and b < h - 1:
            near.append(a)
            far.append(b)
    if len(near) < max(8, int(AUTO_MIN_COL_FRAC * wr)):
        return None
    return float(np.median(near)), float(np.median(far)), len(near)


def _two_lines(region):
    """Per-scanline detection of two parallel dark lines in ``region``.

    Scans each column, keeps the two deepest dark troughs (below that column's
    own bright level -- robust to uneven lighting), and requires them to be
    well separated. The medians of the near/far troughs give the two line
    positions. Unlike a collapsed 1-D profile this survives a **tilted** edge
    and an edge that is faint in only part of the frame, because every scan line
    votes independently. Returns ``(pos_near, pos_far, n_support)`` or None.
    """
    h, wr = region.shape
    near, far = [], []
    for x in range(wr):
        col = gaussian_filter1d(region[:, x].astype(np.float64), EDGE_SMOOTH)
        thr = float(np.percentile(col, 80)) - DARK_MIN_DEPTH
        troughs = [r for r in range(1, h - 1)
                   if col[r] < thr and col[r] <= col[r - 1] and col[r] <= col[r + 1]]
        if len(troughs) < 2:
            continue
        a, b = sorted(sorted(troughs, key=lambda r: col[r])[:2])
        if b - a >= AUTO_MIN_SEP_FRAC * h:
            near.append(a)
            far.append(b)
    if len(near) < max(8, int(AUTO_MIN_COL_FRAC * wr)):
        return None
    return float(np.median(near)), float(np.median(far)), len(near)


def auto_rois(gray, region_frac=1.0 / 3.0, band=8):
    """Auto-find the block's two reference edges in the left ``region_frac`` of the
    frame and return ``(roi1, roi2, fit_mode)`` -- an ROI around each edge plus the
    edge-locus to fit them with (avoids the nozzle/reflection clutter on the
    right). A BRIGHT block (white bar on dark -> ``"step"`` edges) is tried first,
    then a dark chamfer-line block (``"outer"``), in both orientations; the
    candidate present in the most scan lines wins. Raises if neither block
    presents two clear, well-separated edges in most scan lines.
    """
    gray = gray.astype(np.float64)
    h, w = gray.shape
    x_hi = max(12, int(round(w * region_frac)))
    region = gray[:, :x_hi]

    # (fit_mode, orient, (near, far, support)); scan columns for a horizontal
    # edge, rows (transpose) for a vertical one.
    cands = []
    for orient, reg in (("h", region), ("v", region.T)):
        bright = _two_edges_bright(reg)
        if bright:
            cands.append(("step", orient, bright))
        dark = _two_lines(reg)
        if dark:
            cands.append(("outer", orient, dark))
    if not cands:
        raise RuntimeError(
            "Auto-calibrate could not find two clear block edges in the left "
            "third (most scan lines show fewer than two). Reposition so BOTH "
            "block edges are inside the frame (in the left third) with clear "
            "space between them, then re-capture -- or use the manual ROI "
            "'Calibrate Scale'."
        )
    fit_mode, orient, (i1, i2, _) = max(cands, key=lambda c: c[2][2])
    i1, i2 = int(round(i1)), int(round(i2))
    mx = max(2, int(0.04 * x_hi))
    if orient == "h":                      # horizontal edges at rows i1, i2
        return ((mx, i1 - band, x_hi - mx, i1 + band),
                (mx, i2 - band, x_hi - mx, i2 + band),
                fit_mode)
    my = max(2, int(0.04 * h))             # vertical edges at cols i1, i2
    return ((i1 - band, my, i1 + band, h - my),
            (i2 - band, my, i2 + band, h - my),
            fit_mode)


def auto_calibrate_image(image_path, ref_mm, region_frac=1.0 / 3.0, save=True):
    """Auto ROI + block-edge calibration from a still (no manual boxes)."""
    gray = ma.load_gray(Path(image_path))
    roi1, roi2, fit_mode = auto_rois(gray, region_frac)
    result = calibrate_from_rois(gray, roi1, roi2, ref_mm, mode=fit_mode)
    return save_calibration(result, image_path, save_json=save)


def measure_block_size(image_path, region_frac=1.0 / 3.0, save=True):
    """Measure the two-edge distance of a block in **mm** using the stored scale.

    Auto-detects the two block edges (left ``region_frac``, same as auto-calibrate),
    takes the edge-to-edge pixel gap, and multiplies by the calibrated
    ``mm_per_px``. Does NOT change ``calibration.json``. Writes a
    ``*_measured.bmp`` overlay.
    """
    cal = load_calibration()
    if not cal:
        raise RuntimeError(
            "No scale calibration found. Calibrate on a known reference block "
            "first (Calibrate Scale / Auto Calibrate)."
        )
    mm_per_px = float(cal["mm_per_px"])
    image_path = Path(image_path)
    gray = ma.load_gray(image_path)
    roi1, roi2, fit_mode = auto_rois(gray, region_frac)
    result = calibrate_from_rois(gray, roi1, roi2, ref_mm=1.0, mode=fit_mode)
    gap = result["gap_px"]
    mm = gap * mm_per_px
    result["ref_mm"] = mm            # so the connector/labels read in mm

    out_path = image_path.with_name(image_path.stem + "_measured.bmp")
    if save:
        lines = [f"size = {mm:.3f} mm",
                 f"{gap:.1f} px @ {mm_per_px:.5f} mm/px"]
        cv2.imwrite(str(out_path), annotate(gray, result, text_lines=lines))
    return {
        "mm": mm,
        "gap_px": gap,
        "mm_per_px": mm_per_px,
        "image": str(image_path),
        "annotated": str(out_path),
        "calibration_ref_mm": float(cal.get("ref_mm", 0.0)),
    }


def load_calibration():
    """Return the stored calibration dict, or None if not calibrated yet."""
    cal_path = settings_path(CALIBRATION_FILE)
    if not cal_path.exists():
        return None
    try:
        return json.loads(cal_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="still image of the reference block")
    parser.add_argument("--ref-mm", type=float, default=10.0,
                        help="distance between the two edges in mm (default 10)")
    parser.add_argument("--roi1", type=int, nargs=4, required=True,
                        metavar=("X0", "Y0", "X1", "Y1"), help="ROI around edge 1")
    parser.add_argument("--roi2", type=int, nargs=4, required=True,
                        metavar=("X0", "Y0", "X1", "Y1"), help="ROI around edge 2")
    parser.add_argument("--mode",
                        choices=("auto", "outer", "dark", "bright", "step"),
                        default="auto",
                        help="'auto' (default) picks 'step' for a bright block "
                             "edge or 'outer' for a dark chamfer line; else force "
                             "the feature extremum (outer flank, dark-line centre, "
                             "bright peak, or gradient step)")
    args = parser.parse_args()

    r = calibrate(args.image, args.roi1, args.roi2, args.ref_mm, mode=args.mode)
    print(f"image      : {r['image']}")
    print(f"gap        : {r['ref_mm']:g} mm = {r['gap_px']:.2f} px")
    print(f"scale      : {r['mm_per_px']:.5f} mm/px  ({r['px_per_mm']:.2f} px/mm)")
    print(f"saved      : {r.get('calibration_file', '(not saved)')}")
    print(f"check image: {r['annotated']}")


if __name__ == "__main__":
    main()
