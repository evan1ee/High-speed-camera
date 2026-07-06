#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Spray-angle measurement for a white water jet on a dark background.

Canonical high-speed-imaging pipeline:

    Load image -> Gaussian blur -> Otsu threshold -> largest connected
    component -> column-wise gradient edge extraction with subpixel refinement
    -> Savitzky-Golay smoothing -> ROI selection -> RANSAC outlier rejection ->
    Total Least Squares (orthogonal) line fitting -> spray-angle calculation ->
    visualization & report.

Built on OpenCV, NumPy, SciPy and scikit-learn. It is robust against small
droplets, splash artifacts, uneven illumination and partial edge gaps (the
largest-component step removes isolated droplets, Savitzky-Golay smooths local
noise, and RANSAC rejects outlier edge points).

Rig note: the frames here also contain a static, bright nozzle/holder. A
per-pixel temporal-median background is subtracted first (when a folder of
frames is available) so Otsu sees only the moving jet. For a single standalone
image the pipeline runs directly on the grayscale.
"""

import argparse
from math import atan, atan2, degrees
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import savgol_filter
from sklearn.linear_model import LinearRegression, RANSACRegressor

from hsc import injection_extract
from hsc import reference_lines


# ---- Pipeline parameters -------------------------------------------------
DEST_FOLDER_NAME = "measure"
IMAGE_EXTENSIONS = (".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff")

GAUSS_KSIZE = 5            # Gaussian blur kernel (odd): 3 or 5
SAVGOL_WINDOW = 21         # Savitzky-Golay window length (odd)
SAVGOL_POLY = 3            # Savitzky-Golay polynomial order
EDGE_PAD = 3              # search this many px beyond the jet region for the edge
EDGE_SMOOTH = 1.0          # vertical smoothing of the raw column before the edge
# The Otsu mask comes from the background-subtracted image; when the jet is very
# steady the temporal-median background contains the jet core, so subtraction
# removes it and the mask stops SHORT of the visible edge (clipped on the side
# where the static background is bright). Before searching, extend each column's
# band OUTWARD along the raw image while it stays above background, so the true
# gradient ramp is inside the band. Only fires when the mask boundary still sits
# on bright pixels (the truncated case); a correct mask boundary already has
# background just outside it, so the walk stops immediately.
EDGE_BAND_FRAC = 0.15      # "still bright": raw > bg + this*(core - bg)
EDGE_BAND_MAX = 12         # cap the outward extension (px) per side
# Visible-edge refinement: the gradient peak marks the ~50% point of the
# intensity ramp, but the eye reads "white" out to a lower fraction, so the raw
# gradient locus sits ~0.5-1 px inside the visible edge (worst on thin jets).
# A second candidate locus walks OUTWARD from the gradient peak to where the
# column crosses bg + EDGE_VISIBLE_FRAC * (core - bg), normalized per column
# and per side (so it does not tilt with brightness like a global threshold),
# interpolated to subpixel and bounded to EDGE_REFINE_SPAN px.
# Neither locus is universally better: the crossing matches the visible edge on
# clean sharp ramps, but on a skirt/reflection edge its shallow slope amplifies
# intensity noise into position noise, where the gradient peak (steepest slope)
# is the stable choice. measure_frame therefore fits BOTH candidates per edge
# and keeps the one whose points form the straighter line (lower robust
# residual, with EDGE_PICK_TOL preference for the visible locus on ties).
# Set EDGE_VISIBLE_FRAC = None to restore pure gradient-peak edges.
EDGE_VISIBLE_FRAC = 0.25
EDGE_REFINE_SPAN = 3       # px beyond the gradient peak to search for the crossing
EDGE_PICK_TOL = 1.10       # visible locus wins unless grad is >10% straighter

NOZZLE_SIDE = +1           # +1: nozzle on the right of the frame, -1: left
NOZZLE_SKIP = 14           # exclude this many px next to the nozzle (origin)
ROI_FRAC = 0.85            # use this fraction of the jet length (drop breakup)
RANSAC_RESIDUAL = 2.5      # px; inlier tolerance for the RANSAC line fit

MIN_PEAK = 80              # a jet is present only if peak brightness >= this
MIN_AREA = 120             # ... and the bright blob is at least this many px
MIN_POINTS = 12            # minimum edge points needed to fit

# Which jet frames to measure, 1-based from the first frame that has a jet.
MEASURE_START = 10
MEASURE_END = 20

# Visualization
SUPERSAMPLE = 3            # render scale for thin, smooth lines
MEASURE_RENDER_SCALE = 1   # saved measure-frame size = capture size (1 = native 320x240);
                           # set to 3 for supersampled 960x720 output (more zoom detail)
MEASURE_LINE_SS = 2        # draw at this supersample then area-downscale to the output size,
                           # so lines end up ~1/MEASURE_LINE_SS px thick (2 -> half-thickness)
APEX_GAP = NOZZLE_SKIP     # lines start this far from the nozzle (== ROI start)
LINE_COLOR = (0, 255, 0)   # BGR -> green

# ---- Line-quality evaluation standard -------------------------------------
# Each frame gets a 0-100 quality score = min of three sub-scores (weakest link):
#   fit      : robust RMS of the raw subpixel edge points vs the fitted line
#              (px; measures how straight/clean the detected edge is)
#   coverage : fraction of ROI columns that produced an edge point
#              (gaps = mist/dropout interrupting the edge)
#   span     : this frame's jet length vs the longest jet in the run
#              (a collapsing span = injection decay -> unreliable angle)
# Sub-scores map linearly from the GOOD threshold (100) to the BAD one (0).
QUALITY_RMS_GOOD = 0.25    # px  <= this -> 100
QUALITY_RMS_BAD = 1.0      # px  >= this -> 0
QUALITY_COV_GOOD = 0.98    # >= this -> 100
QUALITY_COV_BAD = 0.80     # <= this -> 0
QUALITY_SPAN_GOOD = 0.92   # >= this -> 100 (jet at full length)
QUALITY_SPAN_BAD = 0.60    # <= this -> 0   (jet collapsed to 60%)
# Run-level angle repeatability (std deg across measured frames).
QUALITY_STD_GOOD = 0.06    # deg <= this -> 100
QUALITY_STD_BAD = 0.30     # deg >= this -> 0
CONF_HIGH = 75             # score >= this  -> High
CONF_MEDIUM = 50           # score >= this  -> Medium, else Low
CONF_COLORS = {            # BGR text color per confidence level
    "High": (0, 255, 0),
    "Medium": (0, 255, 255),
    "Low": (0, 0, 255),
}


# ---- I/O -----------------------------------------------------------------
def list_frames(source_dir):
    return injection_extract.list_frames(source_dir)


def load_gray(path):
    """Read a grayscale image (BMP/PNG/TIFF). Fast path for raw 8-bit BMP."""
    info = injection_extract._bmp_info(path)
    if info is not None and info[3] == 8:
        offset, width, height, _ = info
        data = np.fromfile(path, dtype=np.uint8)
        if data.size >= offset + width * height:
            return data[offset : offset + width * height].reshape(height, width)
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Cannot read image: {path}")
    return img


def compute_background(files, sample=80):
    """Per-pixel temporal median over a sampling of frames (static scene)."""
    idx = np.linspace(0, len(files) - 1, min(sample, len(files))).astype(int)
    stack = np.stack([load_gray(files[i]) for i in idx])
    return np.median(stack, axis=0).astype(np.int16)


# ---- Pipeline steps ------------------------------------------------------
def preprocess(gray, bg=None):
    """Return the working grayscale: jet bright on a dark background.

    With a background it returns the (clipped) difference, which removes the
    static nozzle/holder; without one it returns the raw image unchanged.
    """
    if bg is None:
        return gray.astype(np.uint8)
    return np.clip(gray.astype(np.int16) - bg, 0, 255).astype(np.uint8)


def otsu_mask(blurred):
    """Otsu threshold -> binary mask (uint8 0/255)."""
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return mask


def largest_component(mask):
    """Keep only the largest connected component (the main jet)."""
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n_labels < 2:
        return None, 0
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = int(stats[idx, cv2.CC_STAT_AREA])
    return labels == idx, area


def _parabolic_vertex_offset(g, i):
    """Sub-sample offset (in [-0.5, 0.5]) of a gradient extremum near index ``i``.

    Fits a parabola through the three samples g[i-1], g[i], g[i+1] and returns
    the offset of its vertex from ``i``. Works for a maximum (upper edge) or a
    minimum (lower edge). Falls back to 0.0 (the integer position) when the peak
    sits on the search boundary or the three samples are colinear/noisy.
    """
    n = len(g)
    if i <= 0 or i >= n - 1:
        return 0.0
    a, b, c = float(g[i - 1]), float(g[i]), float(g[i + 1])
    denom = a - 2.0 * b + c
    if denom == 0.0:
        return 0.0
    offset = 0.5 * (a - c) / denom
    if not np.isfinite(offset) or abs(offset) > 0.5:
        return 0.0
    return offset


def _visible_edge_crossing(seg, peak, core, is_top, frac, span):
    """Subpixel row where the column crosses ``bg + frac*(core - bg)``.

    Walks OUTWARD (away from the bright core) from the gradient peak until the
    smoothed column drops below the per-column, per-side threshold, then
    linearly interpolates the crossing. Returns None (caller falls back to the
    gradient vertex) if there is no crossing within ``span`` px -- e.g. the
    band is clipped by the image border or the ramp never settles.
    """
    core_val = float(seg[core])
    bg = float(seg[: core + 1].min() if is_top else seg[core:].min())
    if core_val - bg < 1e-6:
        return None
    t = bg + frac * (core_val - bg)
    if is_top:
        for row in range(peak, max(0, peak - span) - 1, -1):
            if seg[row] < t:
                denom = float(seg[row + 1]) - float(seg[row])
                if denom <= 0:
                    return float(row)
                return row + (t - float(seg[row])) / denom
        return None
    for row in range(peak, min(len(seg) - 1, peak + span) + 1):
        if seg[row] < t:
            denom = float(seg[row - 1]) - float(seg[row])
            if denom <= 0:
                return float(row)
            return (row - 1) + (float(seg[row - 1]) - t) / denom
    return None


def extract_edges(gray, comp, pad=EDGE_PAD, smooth=EDGE_SMOOTH,
                  return_candidates=False):
    """Column-wise edges within the jet region (largest Otsu component).

    The Otsu/largest-component step locates the jet column-band (and excludes
    the static nozzle and isolated droplets). Within each column's band the
    edge is the point of steepest intensity change on the *raw* image -- the
    steepest rise above the bright core (upper edge) and the steepest fall
    below it (lower edge). The gradient adapts to each side's own fall-off, so
    it tracks the visible white edge even when the jet is asymmetric (a brighter
    skirt or reflection on one side) -- which a fixed brightness fraction does
    not. A binary-mask boundary, being brightness-dependent, also tilts where
    the jet is brighter, so it does not match the flat visible edge.

    Each gradient peak is refined to subpixel precision by parabolic
    interpolation of the three gradient samples straddling the peak, so the
    returned edge positions are continuous (float), not integer rows.

    With ``return_candidates=True`` the return value is
    ``(xs, (y_top_grad, y_top_vis), (y_bot_grad, y_bot_vis))`` -- the gradient
    locus plus the visible-edge crossing locus (see EDGE_VISIBLE_FRAC) so the
    caller can pick the straighter one per edge. The default 3-tuple returns
    the gradient locus only.
    """
    h = gray.shape[0]
    col_smooth = gaussian_filter1d(gray.astype(np.float64), smooth, axis=0)
    want_vis = return_candidates and EDGE_VISIBLE_FRAC is not None
    xs, y_top, y_bot, y_top_v, y_bot_v = [], [], [], [], []
    for x in np.where(comp.any(axis=0))[0]:
        rows = np.where(comp[:, x])[0]
        rtop, rbot = int(rows.min()), int(rows.max())
        # Extend the band outward along the raw column while it is still bright,
        # recovering edges the background subtraction clipped from the mask.
        col = col_smooth[:, x]
        core_val = float(col[rtop : rbot + 1].max())
        bg_level = float(np.percentile(col, 20))
        thr = bg_level + EDGE_BAND_FRAC * (core_val - bg_level)
        up = rtop
        while up > 0 and col[up - 1] > thr and (rtop - up) < EDGE_BAND_MAX:
            up -= 1
        dn = rbot
        while dn < h - 1 and col[dn + 1] > thr and (dn - rbot) < EDGE_BAND_MAX:
            dn += 1
        r0 = max(0, up - pad)
        r1 = min(h - 1, dn + pad)
        seg = col_smooth[r0 : r1 + 1, x]
        core = int(np.argmax(seg))
        grad = np.gradient(seg)
        # Integer gradient peaks: steepest rise above the core, steepest fall below.
        it = int(np.argmax(grad[:core])) if core >= 1 else 0
        ib = core + int(np.argmin(grad[core:])) if core < seg.size - 1 else seg.size - 1
        top = r0 + it + _parabolic_vertex_offset(grad, it)
        bot = r0 + ib + _parabolic_vertex_offset(grad, ib)
        xs.append(int(x))
        y_top.append(float(top))
        y_bot.append(float(bot))
        if want_vis:
            tv = _visible_edge_crossing(
                seg, it, core, True, EDGE_VISIBLE_FRAC, EDGE_REFINE_SPAN
            ) if core >= 1 else None
            bv = _visible_edge_crossing(
                seg, ib, core, False, EDGE_VISIBLE_FRAC, EDGE_REFINE_SPAN
            ) if core < seg.size - 1 else None
            y_top_v.append(float(r0 + tv) if tv is not None else float(top))
            y_bot_v.append(float(r0 + bv) if bv is not None else float(bot))
    xs = np.array(xs)
    y_top, y_bot = np.array(y_top), np.array(y_bot)
    if not return_candidates:
        return xs, y_top, y_bot
    if not want_vis:
        return xs, (y_top, y_top.copy()), (y_bot, y_bot.copy())
    return xs, (y_top, np.array(y_top_v)), (y_bot, np.array(y_bot_v))


def _pick_edge_locus(xr, grad_roi, vis_roi, tol=EDGE_PICK_TOL):
    """Choose gradient vs visible-edge points for one edge: the straighter wins.

    Straightness = robust sigma of the ROI points around their own least-squares
    line. The visible locus is preferred (it matches what the eye sees) unless
    the gradient locus is more than ``tol``x straighter -- which happens on
    skirt/reflection edges where the threshold crossing is noise-amplified.
    Returns (chosen_full_array_selector, sigma) as a bool: True = visible.
    """
    if xr.size < 2 or np.array_equal(grad_roi, vis_roi):
        return False
    def sigma(y):
        k, b = np.polyfit(xr, y, 1)
        return _robust_sigma(y - (k * xr + b))
    return sigma(vis_roi) <= tol * sigma(grad_roi)


def smooth_edges(y, window=SAVGOL_WINDOW, poly=SAVGOL_POLY):
    """Savitzky-Golay smoothing of an edge curve (keeps shape, drops noise)."""
    n = len(y)
    if n < poly + 2:
        return y.astype(float)
    win = min(window, n if n % 2 == 1 else n - 1)
    if win % 2 == 0:
        win -= 1
    if win <= poly:
        return y.astype(float)
    return savgol_filter(y.astype(float), win, poly)


def select_roi(xs, start_x=None, end_x=None):
    """Boolean mask over the stable jet region (drop nozzle + breakup).

    If start_x/end_x are not given they are derived: skip NOZZLE_SKIP px next
    to the nozzle (origin) and keep ROI_FRAC of the jet length.
    """
    x_lo, x_hi = int(xs.min()), int(xs.max())
    span = x_hi - x_lo
    if start_x is None or end_x is None:
        if NOZZLE_SIDE > 0:                    # nozzle on the right (high x)
            hi = x_hi - NOZZLE_SKIP
            lo = max(x_lo, hi - ROI_FRAC * span)
        else:                                  # nozzle on the left (low x)
            lo = x_lo + NOZZLE_SKIP
            hi = min(x_hi, lo + ROI_FRAC * span)
        start_x, end_x = lo, hi
    roi = (xs >= start_x) & (xs <= end_x)
    return roi, start_x, end_x


def _tls_direction(x, y):
    """Total-least-squares line via PCA (largest-variance eigenvector).

    Returns ``(slope, intercept, vx, vy)`` where ``(vx, vy)`` is the unit
    direction of the fitted line (canonically ``vx >= 0``). Unlike ordinary
    least squares, which assumes x is exact and only y is noisy, TLS minimizes
    the orthogonal distance to the line -- correct here because both edge
    coordinates carry uncertainty.
    """
    pts = np.column_stack([x.astype(float), y.astype(float)])
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    cov = np.cov(centered.T)                       # 2x2 covariance
    eigvals, eigvecs = np.linalg.eigh(cov)         # ascending eigenvalues
    vx, vy = eigvecs[:, int(np.argmax(eigvals))]   # major axis == line direction
    if vx < 0:                                     # canonical orientation
        vx, vy = -vx, -vy
    if abs(vx) < 1e-12:                            # (near-)vertical: slope undefined
        slope = float(np.sign(vy) or 1.0) * 1e12
    else:
        slope = float(vy / vx)
    intercept = float(centroid[1] - slope * centroid[0])
    return slope, intercept, float(vx), float(vy)


def tls_fit(x, y, residual_threshold=RANSAC_RESIDUAL):
    """RANSAC outlier rejection, then Total Least Squares on the inliers.

    RANSAC (with an ordinary least-squares model) rejects droplet / splash /
    breakup outliers; the surviving inliers are then fit with orthogonal-distance
    TLS. Returns ``(slope, intercept, n_inliers, vx, vy)``.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    inliers = np.ones(x.size, dtype=bool)
    if x.size >= 2:
        try:
            model = RANSACRegressor(
                LinearRegression(), residual_threshold=residual_threshold,
                random_state=0,
            )
            model.fit(x.reshape(-1, 1), y)
            mask = model.inlier_mask_
            if int(mask.sum()) >= 2:
                inliers = mask
        except ValueError:
            pass                                   # degenerate fit -> keep all points
    slope, intercept, vx, vy = _tls_direction(x[inliers], y[inliers])
    return slope, intercept, int(inliers.sum()), vx, vy


def spray_angle(k_upper, k_lower):
    """Total spray angle (degrees, 0..180) between the two edge lines."""
    return abs(degrees(atan(k_upper) - atan(k_lower)))


def line_angle_deg(d1, d2):
    """Acute angle (degrees, 0..90) between two undirected lines given their
    direction vectors ``d1``/``d2``."""
    dot = float(d1[0] * d2[0] + d1[1] * d2[1])
    cross = float(d1[0] * d2[1] - d1[1] * d2[0])
    return float(degrees(atan2(abs(cross), abs(dot))))


# ---- Quality / confidence --------------------------------------------------
def _robust_sigma(residuals):
    """Outlier-resistant spread (px) of edge residuals: 1.4826 * MAD."""
    residuals = np.asarray(residuals, dtype=float)
    if residuals.size == 0:
        return 0.0
    med = float(np.median(residuals))
    return float(1.4826 * np.median(np.abs(residuals - med)))


def _ramp_score(value, good, bad):
    """Map value -> 0..100: 100 at/beyond `good`, 0 at/beyond `bad`, linear between."""
    if good == bad:
        return 100.0 if value == good else 0.0
    t = (value - bad) / (good - bad)
    return float(np.clip(t, 0.0, 1.0) * 100.0)


def confidence_level(score):
    """Map a 0-100 quality score to High / Medium / Low."""
    if score >= CONF_HIGH:
        return "High"
    if score >= CONF_MEDIUM:
        return "Medium"
    return "Low"


def frame_quality(result, span_ratio):
    """Per-frame quality score (0-100) and sub-scores from the fit metrics.

    Weakest-link rule: the frame is only as trustworthy as its worst aspect.
    """
    rms = max(result["rms_upper"], result["rms_lower"])
    s_fit = _ramp_score(rms, QUALITY_RMS_GOOD, QUALITY_RMS_BAD)
    s_cov = _ramp_score(result["coverage"], QUALITY_COV_GOOD, QUALITY_COV_BAD)
    s_span = _ramp_score(span_ratio, QUALITY_SPAN_GOOD, QUALITY_SPAN_BAD)
    score = min(s_fit, s_cov, s_span)
    return score, {"fit": s_fit, "coverage": s_cov, "span": s_span}


# ---- Per-frame orchestration --------------------------------------------
def measure_frame(gray, bg=None, start_x=None, end_x=None, line_frac=None):
    """Run the full pipeline on one frame.

    Returns a dict (angle, slopes, edge points, fitted line endpoints) or None
    if there is no measurable jet.
    """
    work = preprocess(gray, bg)
    if float(np.percentile(work, 99.5)) < MIN_PEAK:
        return None

    blurred = cv2.GaussianBlur(work, (GAUSS_KSIZE, GAUSS_KSIZE), 0)
    mask = otsu_mask(blurred)
    comp, area = largest_component(mask)
    if comp is None or area < MIN_AREA:
        return None

    xs, top_cands, bot_cands = extract_edges(gray, comp, return_candidates=True)
    if xs.size < MIN_POINTS:
        return None

    roi, sx, ex = select_roi(xs, start_x, end_x)
    if int(roi.sum()) < MIN_POINTS:
        return None
    xr = xs[roi]

    # Per-edge locus selection: visible-edge crossing where it is stable,
    # gradient peak where the crossing is noise-amplified (skirt/reflection).
    y_top = top_cands[1] if _pick_edge_locus(
        xr.astype(float), top_cands[0][roi], top_cands[1][roi]) else top_cands[0]
    y_bot = bot_cands[1] if _pick_edge_locus(
        xr.astype(float), bot_cands[0][roi], bot_cands[1][roi]) else bot_cands[0]

    y_top_s = smooth_edges(y_top)
    y_bot_s = smooth_edges(y_bot)
    k_up, b_up, n_up, vx_up, vy_up = tls_fit(xr, y_top_s[roi])
    k_lo, b_lo, n_lo, vx_lo, vy_lo = tls_fit(xr, y_bot_s[roi])

    angle = spray_angle(k_up, k_lo)

    # Quality metrics (evaluation standard): how well the drawn line matches the
    # detected edge. Residuals use the RAW subpixel edges (pre-smoothing) so the
    # Savitzky-Golay filter cannot hide edge noise; robust sigma ignores the few
    # splash outliers RANSAC also rejects.
    rms_up = _robust_sigma(y_top[roi] - (k_up * xr + b_up))
    rms_lo = _robust_sigma(y_bot[roi] - (k_lo * xr + b_lo))
    roi_width = float(ex - sx) + 1.0
    coverage = float(len(xr)) / roi_width if roi_width > 0 else 0.0
    jet_span = float(xs.max() - xs.min())
    width = gray.shape[1]
    if line_frac is not None:
        # Draw from the image left side out to `line_frac` of the width.
        xa, xb = 0.0, float(line_frac) * (width - 1)
    elif NOZZLE_SIDE > 0:               # nozzle on the right -> draw to left edge
        xa, xb = float(ex), 0.0
    else:                               # nozzle on the left -> draw to right edge
        xa, xb = float(sx), float(width - 1)
    return {
        "angle": angle,
        "k_upper": k_up,
        "k_lower": k_lo,
        "n_points": int(roi.sum()),
        "n_inliers": n_up + n_lo,
        "dir_upper": (vx_up, vy_up),
        "dir_lower": (vx_lo, vy_lo),
        "rms_upper": rms_up,
        "rms_lower": rms_lo,
        "coverage": min(coverage, 1.0),
        "jet_span": jet_span,
        "roi": (float(sx), float(ex)),
        "up0": np.array([xa, k_up * xa + b_up]),
        "up1": np.array([xb, k_up * xb + b_up]),
        "lo0": np.array([xa, k_lo * xa + b_lo]),
        "lo1": np.array([xb, k_lo * xb + b_lo]),
        "edges": (xs, y_top_s, y_bot_s),
    }


def _clip_lines_to_x(result, x_lo, x_hi):
    """Rewrite the fitted green-line endpoints so each edge line spans only the
    x-window ``[x_lo, x_hi]`` -- used to confine the drawing to the reference
    rectangle. The fit (slope/angle) is unchanged; only the drawn extent is."""
    for p0, p1, kname in (("up0", "up1", "k_upper"), ("lo0", "lo1", "k_lower")):
        k = result[kname]
        b = float(result[p0][1]) - k * float(result[p0][0])
        result[p0] = np.array([x_hi, k * x_hi + b])
        result[p1] = np.array([x_lo, k * x_lo + b])


def annotate(gray, result, scale=SUPERSAMPLE, show_edges=False):
    """Render the result: thin green RANSAC lines + angle (supersampled)."""
    big = cv2.resize(
        gray, (gray.shape[1] * scale, gray.shape[0] * scale),
        interpolation=cv2.INTER_CUBIC,
    )
    img = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
    if show_edges:
        xs, yt, yb = result["edges"]
        for x, t, b in zip(xs, yt, yb):
            img[int(round(t * scale)), int(round(x * scale))] = (60, 60, 255)
            img[int(round(b * scale)), int(round(x * scale))] = (255, 60, 60)
    pt = lambda k: tuple(np.round(result[k] * scale).astype(int))
    cv2.line(img, pt("up0"), pt("up1"), LINE_COLOR, 1, cv2.LINE_AA)
    cv2.line(img, pt("lo0"), pt("lo1"), LINE_COLOR, 1, cv2.LINE_AA)
    cv2.putText(
        img, f"{result['angle']:.2f}", (6 * scale, 16 * scale),
        cv2.FONT_HERSHEY_SIMPLEX, 0.45 * scale, LINE_COLOR, 1, cv2.LINE_AA,
    )
    return img


# ---- Folder workflow -----------------------------------------------------
def measure_folder(source_dir, dest_base=None, start=MEASURE_START, end=MEASURE_END,
                   start_x=None, end_x=None, line_frac=None, progress=None):
    """Measure jet frames ``start`` .. ``end`` (1-based, from the first frame
    that has a jet) and save annotated images + a CSV report."""
    source_dir = Path(source_dir)
    files = list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")
    start = max(1, start)
    end = max(start, end)

    bg = compute_background(files)

    if dest_base is None:
        parents = source_dir.parents
        base = parents[1] if len(parents) > 1 else source_dir.parent
        dest_base = base / DEST_FOLDER_NAME
    dest_dir = injection_extract.make_dest_dir(source_dir, dest_base)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: measure. Annotation happens after, because the span-ratio quality
    # metric needs the longest jet in the run as its reference.
    target = end - start + 1
    measured = []
    jet_count = 0
    for path in files:
        if jet_count >= end:
            break
        gray = load_gray(path)
        result = measure_frame(gray, bg, start_x=start_x, end_x=end_x, line_frac=line_frac)
        if result is None:
            continue
        jet_count += 1
        if jet_count < start:
            continue
        measured.append((path.name, gray, result))
        if progress is not None:
            progress(len(measured), target)

    if not measured:
        raise RuntimeError(
            "No measurable jet found (no frame has a clear spray cone)."
        )

    # Pass 2: quality score + confidence per frame, then annotate and save.
    # If a nozzle reference (tip edge + centerline) was set for this frame size,
    # overlay it on every annotated frame.
    ref = reference_lines.load_reference()
    blue_dir = None
    if ref and ref.get("blue_a") and ref.get("blue_b"):
        ba, bb = ref["blue_a"], ref["blue_b"]
        blue_dir = (bb[0] - ba[0], bb[1] - ba[1])
    span_max = max(r["jet_span"] for _, _, r in measured)
    for name, gray, r in measured:
        span_ratio = r["jet_span"] / span_max if span_max > 0 else 0.0
        score, subs = frame_quality(r, span_ratio)
        r["span_ratio"] = span_ratio
        r["quality"] = score
        r["quality_subscores"] = subs
        r["confidence"] = confidence_level(score)
        has_ref = ref and ref.get("image_size") == [gray.shape[1], gray.shape[0]]
        # Angle vs. the blue centerline: the deviation of each green edge from the
        # spray axis. Report the larger of the two half-angles (the worst edge).
        if has_ref and blue_dir is not None:
            r["angle_upper"] = line_angle_deg(blue_dir, r["dir_upper"])
            r["angle_lower"] = line_angle_deg(blue_dir, r["dir_lower"])
            r["angle"] = max(r["angle_upper"], r["angle_lower"])
        # Confine the green jet lines to the reference rectangle's x-window.
        if has_ref and ref.get("rect"):
            rx0, _, rx1, _ = ref["rect"]
            _clip_lines_to_x(r, min(rx0, rx1), max(rx0, rx1))
        draw_scale = MEASURE_RENDER_SCALE * MEASURE_LINE_SS
        annotated = annotate(gray, r, scale=draw_scale)
        if has_ref:
            reference_lines.draw_reference(annotated, ref, scale=draw_scale)
        if MEASURE_LINE_SS != 1:            # downscale to output size -> thinner lines
            out_w = gray.shape[1] * MEASURE_RENDER_SCALE
            out_h = gray.shape[0] * MEASURE_RENDER_SCALE
            annotated = cv2.resize(annotated, (out_w, out_h), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(dest_dir / name), annotated)

    angles = [r["angle"] for _, _, r in measured]
    angle_std = float(np.std(angles, ddof=1)) if len(angles) > 1 else 0.0
    # Trusted mean: drop Low-confidence frames (typically injection decay) so
    # they cannot drag the reported angle. Falls back to all frames if none pass.
    trusted = [r["angle"] for _, _, r in measured if r["confidence"] != "Low"]
    if not trusted:
        trusted = angles
    trusted_mean = float(np.mean(trusted))
    trusted_std = float(np.std(trusted, ddof=1)) if len(trusted) > 1 else 0.0
    # Run confidence: the measured frames must agree with each other (angle std)
    # AND be individually trustworthy (median frame score).
    s_std = _ramp_score(angle_std, QUALITY_STD_GOOD, QUALITY_STD_BAD)
    s_frames = float(np.median([r["quality"] for _, _, r in measured]))
    run_score = min(s_std, s_frames)
    run_conf = confidence_level(run_score)

    with open(dest_dir / "angles.csv", "w", encoding="utf-8") as fh:
        fh.write("frame,angle_deg,k_upper,k_lower,n_points,"
                 "rms_up_px,rms_lo_px,coverage,span_ratio,quality,confidence\n")
        for name, _, r in measured:
            fh.write(f"{name},{r['angle']:.2f},{r['k_upper']:.5f},"
                     f"{r['k_lower']:.5f},{r['n_points']},"
                     f"{r['rms_upper']:.3f},{r['rms_lower']:.3f},"
                     f"{r['coverage']:.3f},{r['span_ratio']:.3f},"
                     f"{r['quality']:.0f},{r['confidence']}\n")
        fh.write(f"mean,{np.mean(angles):.2f},,,,,,,,,\n")
        fh.write(f"std,{angle_std:.3f},,,,,,,,,\n")
        fh.write(f"trusted_mean,{trusted_mean:.2f},,,{len(trusted)},,,,,,"
                 f"excl. Low frames\n")
        fh.write(f"run_confidence,{run_conf} ({run_score:.0f}),,,,,,,,,\n")

    return {
        "source_dir": str(source_dir),
        "dest_dir": str(dest_dir),
        "measured_count": len(measured),
        "mean_angle": float(np.mean(angles)),
        "min_angle": float(np.min(angles)),
        "max_angle": float(np.max(angles)),
        "angle_std": angle_std,
        "trusted_mean": trusted_mean,
        "trusted_std": trusted_std,
        "trusted_count": len(trusted),
        "run_quality": run_score,
        "confidence": run_conf,
        "frames": [(name, r["angle"]) for name, _, r in measured],
        "frame_confidence": [
            (name, r["quality"], r["confidence"]) for name, _, r in measured
        ],
    }


def measure_single(image_path, dest=None, start_x=None, end_x=None):
    """Measure one standalone image (no temporal background)."""
    image_path = Path(image_path)
    gray = load_gray(image_path)
    result = measure_frame(gray, bg=None, start_x=start_x, end_x=end_x)
    if result is None:
        raise RuntimeError("No measurable jet found in the image.")
    out = Path(dest) if dest else image_path.with_name(image_path.stem + "_measured.png")
    cv2.imwrite(str(out), annotate(gray, result, show_edges=True))
    return result, out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="folder of injection frames OR a single image")
    parser.add_argument("--dest", default=None, help="destination base folder / image path")
    parser.add_argument("--start", type=int, default=MEASURE_START, help="first jet frame (1-based)")
    parser.add_argument("--end", type=int, default=MEASURE_END, help="last jet frame (1-based)")
    parser.add_argument("--start-x", type=int, default=None, help="ROI start column")
    parser.add_argument("--end-x", type=int, default=None, help="ROI end column")
    args = parser.parse_args()

    src = Path(args.source)
    if src.is_file():
        result, out = measure_single(src, args.dest, args.start_x, args.end_x)
        print(f"spray angle : {result['angle']:.2f} deg")
        print(f"k_upper     : {result['k_upper']:.5f}")
        print(f"k_lower     : {result['k_lower']:.5f}")
        print(f"edge points : {result['n_points']}")
        print(f"saved to    : {out}")
        return

    result = measure_folder(src, dest_base=args.dest, start=args.start, end=args.end,
                            start_x=args.start_x, end_x=args.end_x)
    for name, angle in result["frames"]:
        print(f"{name}: {angle:.2f} deg")
    print(f"--- {result['measured_count']} frames, mean {result['mean_angle']:.2f} deg, "
          f"std {result['angle_std']:.3f}, confidence {result['confidence']} "
          f"({result['run_quality']:.0f}/100)")
    print(f"saved to {result['dest_dir']}")


if __name__ == "__main__":
    main()
