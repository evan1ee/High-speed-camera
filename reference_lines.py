#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Nozzle reference lines: the tip-edge line (red) and the centerline (blue).

The user marks the nozzle tip edge as a short line segment (the **red** line);
from it a **centerline** (blue) is constructed through the edge's midpoint,
**perpendicular** to the edge, and extended across the image -- the spray axis.
The reference is stored in ``reference_lines.json`` (via ``data_root()``) so it
can be overlaid on every measured frame while the nozzle/camera stay put.

Coordinates are image pixels at native resolution; drawing scales them.
"""

import json
from pathlib import Path

import cv2
import numpy as np

import injection_extract
from app_paths import data_root


REFERENCE_FILE = "reference_lines.json"
RED = (0, 0, 255)          # BGR - nozzle tip edge / rectangle
BLUE = (255, 128, 0)       # BGR - centerline (spray axis)

# Rectangle reference (a target band along the jet), sized in mm from the red
# line, centered on the blue centerline. Both edges are measured downstream
# (away from the nozzle). Needs the scale calibration (mm/px) to place in pixels.
RECT_NEAR_MM = 1.0         # right edge: this far from the red line (toward the jet)
RECT_FAR_MM = 6.51         # left edge:  this far from the red line
RECT_HEIGHT_MM = 0.775     # full height, centered on the centerline


def _clip_line(point, direction, w, h):
    """Clip the infinite line ``point + t*direction`` to the image rectangle.

    Returns the two border intersection points, or None if the line misses.
    """
    px, py = float(point[0]), float(point[1])
    dx, dy = float(direction[0]), float(direction[1])
    ts = []
    for num, den in (((0 - px), dx), ((w - 1 - px), dx),
                     ((0 - py), dy), ((h - 1 - py), dy)):
        if abs(den) < 1e-9:
            continue
        t = num / den
        x, y = px + t * dx, py + t * dy
        if -1e-6 <= x <= w - 1 + 1e-6 and -1e-6 <= y <= h - 1 + 1e-6:
            ts.append(t)
    if len(ts) < 2:
        return None
    t0, t1 = min(ts), max(ts)
    return ((px + t0 * dx, py + t0 * dy), (px + t1 * dx, py + t1 * dy))


def _load_gray(path):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Cannot read image: {path}")
    return img


def detect_nozzle_tip(gray, nozzle_side=1):
    """Auto-locate the nozzle tip edge as the leftmost (for a right-side nozzle)
    protrusion of the bright nozzle structure. Returns the two endpoints of the
    tip-edge segment ``(p0, p1)`` (a short vertical line at the tip).
    """
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if nozzle_side > 0:                     # nozzle on the right: search right half
        mask[:, : w // 2] = 0
    else:
        mask[:, w // 2:] = 0
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n_lab < 2:
        raise RuntimeError("No bright nozzle structure found to detect the tip.")
    # The nozzle is anchored to the image border on its side; keep only bright
    # components touching that border (excludes a bright calibration block or
    # mid-frame reflections), then take the largest.
    def touches_border(i):
        left = stats[i, cv2.CC_STAT_LEFT]
        right = left + stats[i, cv2.CC_STAT_WIDTH]
        return right >= w - 1 if nozzle_side > 0 else left <= 1
    anchored = [i for i in range(1, n_lab) if touches_border(i)]
    pool = anchored if anchored else list(range(1, n_lab))
    idx = max(pool, key=lambda i: stats[i, cv2.CC_STAT_AREA])
    ys, xs = np.where(labels == idx)
    if nozzle_side > 0:
        x_tip = int(xs.min())
        rows = ys[xs <= x_tip + 3]         # tip-face rows near the leftmost column
    else:
        x_tip = int(xs.max())
        rows = ys[xs >= x_tip - 3]
    y0, y1 = int(rows.min()), int(rows.max())
    return (x_tip, y0), (x_tip, y1)


def detect_tip_in_roi(gray, roi, nozzle_side=1):
    """Detect the nozzle tip edge INSIDE a user-marked ROI.

    The ROI constrains the search to the nozzle tip, so a bright calibration
    block, reflections or the holder elsewhere in the frame can't mislead it.
    Within the ROI it takes the largest bright component and its leftmost (for a
    right-side nozzle) protrusion as the tip edge. Returns ``(p0, p1)`` endpoints
    of the tip-edge segment in full-image coordinates.
    """
    h, w = gray.shape
    x0, y0, x1, y1 = (int(round(v)) for v in roi)
    x0, x1 = sorted((max(0, x0), min(w, x1)))
    y0, y1 = sorted((max(0, y0), min(h, y1)))
    if x1 - x0 < 3 or y1 - y0 < 3:
        raise RuntimeError("Marked area is too small - draw a larger box on the tip.")
    sub = gray[y0:y1, x0:x1]
    blur = cv2.GaussianBlur(sub, (5, 5), 0)
    _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n_lab < 2:
        raise RuntimeError("No bright nozzle edge found inside the marked area.")
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.where(labels == idx)
    if nozzle_side > 0:
        x_tip = int(xs.min())
        rows = ys[xs <= x_tip + 3]
    else:
        x_tip = int(xs.max())
        rows = ys[xs >= x_tip - 3]
    return ((x0 + x_tip, y0 + int(rows.min())),
            (x0 + x_tip, y0 + int(rows.max())))


def build_reference(p0, p1, image_size):
    """Build the reference from a marked nozzle-tip edge segment ``p0``-``p1``.

    ``image_size`` is ``(w, h)``. Returns a dict with the red edge endpoints,
    the midpoint, and the blue centerline endpoints (clipped to the image).
    """
    w, h = int(image_size[0]), int(image_size[1])
    a = np.array(p0, dtype=float)
    b = np.array(p1, dtype=float)
    d = b - a
    length = float(np.hypot(*d))
    if length < 1e-6:
        raise RuntimeError("Nozzle tip edge is too short - drag a longer line.")
    d /= length
    mid = 0.5 * (a + b)
    normal = np.array([-d[1], d[0]])       # perpendicular to the edge
    if normal[0] > 0:                      # orient the centerline toward the jet (left)
        normal = -normal
    clipped = _clip_line(mid, normal, w, h)
    if clipped is None:
        raise RuntimeError("Could not construct the centerline within the image.")
    blue_a, blue_b = clipped
    return {
        "nozzle_p0": [float(a[0]), float(a[1])],
        "nozzle_p1": [float(b[0]), float(b[1])],
        "mid": [float(mid[0]), float(mid[1])],
        "blue_a": [float(blue_a[0]), float(blue_a[1])],
        "blue_b": [float(blue_b[0]), float(blue_b[1])],
        "image_size": [w, h],
    }


def attach_rectangle(ref, mm_per_px, nozzle_side=1,
                     near_mm=RECT_NEAR_MM, far_mm=RECT_FAR_MM,
                     height_mm=RECT_HEIGHT_MM):
    """Add a mm-sized rectangle to ``ref``, built from the red line and centerline.

    The rectangle is centered on the blue centerline; its near/far vertical edges
    sit ``near_mm``/``far_mm`` downstream of the red line (away from the nozzle),
    and it is ``height_mm`` tall. Pixel corners are computed with ``mm_per_px``.
    """
    red_x = ref["nozzle_p0"][0]
    cy = ref["mid"][1]
    x_near = red_x - nozzle_side * (near_mm / mm_per_px)
    x_far = red_x - nozzle_side * (far_mm / mm_per_px)
    hh = 0.5 * height_mm / mm_per_px
    x0, x1 = sorted((x_near, x_far))
    ref["rect"] = [x0, cy - hh, x1, cy + hh]
    ref["rect_near_mm"] = near_mm
    ref["rect_far_mm"] = far_mm
    ref["rect_height_mm"] = height_mm
    ref["rect_mm_per_px"] = mm_per_px
    return ref


def draw_reference(img_bgr, ref, scale=1, width=1):
    """Draw the red tip-edge line, blue centerline, and (if set) the rectangle."""
    def pt(xy):
        return (int(round(xy[0] * scale)), int(round(xy[1] * scale)))
    cv2.line(img_bgr, pt(ref["blue_a"]), pt(ref["blue_b"]), BLUE, width, cv2.LINE_AA)
    cv2.line(img_bgr, pt(ref["nozzle_p0"]), pt(ref["nozzle_p1"]), RED, width, cv2.LINE_AA)
    if ref.get("rect"):
        x0, y0, x1, y1 = ref["rect"]
        cv2.rectangle(img_bgr, pt((x0, y0)), pt((x1, y1)), RED, width, cv2.LINE_AA)
    return img_bgr


def _background(source_dir, sample=60):
    """Per-pixel temporal median of a folder's frames -- the static nozzle
    without any jet (the cleanest image to detect the tip on)."""
    files = injection_extract.list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")
    idx = np.linspace(0, len(files) - 1, min(sample, len(files))).astype(int)
    stack = np.stack([_load_gray(files[i]) for i in idx])
    return np.median(stack, axis=0).astype(np.uint8)


def _finish_reference(gray, nozzle_side, out_path, source, save):
    h, w = gray.shape
    p0, p1 = detect_nozzle_tip(gray, nozzle_side)
    ref = build_reference(p0, p1, (w, h))
    big = cv2.resize(gray, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)
    vis = draw_reference(cv2.cvtColor(big, cv2.COLOR_GRAY2BGR), ref, scale=3)
    cv2.imwrite(str(out_path), vis)
    ref["source"] = str(source)
    ref["annotated"] = str(out_path)
    if save:
        ref["reference_file"] = save_reference(ref)
    return ref


def set_reference_from_folder(source_dir, nozzle_side=1, save=True):
    """Detect the nozzle tip on a folder's temporal-median background (best:
    the static nozzle with no jet), then build + store the reference."""
    bg = _background(source_dir)
    out = data_root() / "reference_lines_check.bmp"
    return _finish_reference(bg, nozzle_side, out, source_dir, save)


def set_reference_from_image(image_path, nozzle_side=1, save=True):
    """Auto-detect the nozzle tip on a single still, build + store the reference."""
    image_path = Path(image_path)
    gray = _load_gray(image_path)
    out = image_path.with_name(image_path.stem + "_ref.bmp")
    return _finish_reference(gray, nozzle_side, out, image_path, save)


def save_check_image(gray, ref, out_path):
    """Write a native-resolution (not supersampled) overlay for confirmation."""
    vis = draw_reference(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), ref, scale=1)
    cv2.imwrite(str(out_path), vis)
    return str(out_path)


def save_reference(ref):
    path = data_root() / REFERENCE_FILE
    path.write_text(json.dumps(ref, indent=2), encoding="utf-8")
    return str(path)


def load_reference():
    """Return the stored reference dict, or None if not set yet."""
    path = data_root() / REFERENCE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
