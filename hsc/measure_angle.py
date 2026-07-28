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
import json
from contextlib import contextmanager
from math import atan, atan2, degrees
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter
from scipy.special import erf as _scipy_erf
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

# ---- erf (blurred-step) edge model ------------------------------------------
# The gradient peak marks the ~50% ramp point and the visible-crossing walks a
# fixed fraction -- both are biased when one side has a slow skirt/reflection
# falloff. Fitting I(y) = base + amp*Phi((y-mu)/sigma) per column PER SIDE gives
# the true step center mu with that side's own base/amp/sigma, so a skirted
# lower edge no longer drags its fitted line. Selected per edge by the same
# straightness contest as the visible locus (EDGE_PICK_TOL).
EDGE_MODEL = "legacy"        # "erf" is part of the opt-in edge-detection V2 set
ERF_FIT_HALF = 5             # fit window: peak +/- this many px
ERF_SIGMA_MAX = 5.0          # reject wider ramps as "no edge here"
ERF_MIN_AMP = 8.0            # reject fits with less contrast than this

# ---- Background construction ----------------------------------------------
# "window"   : temporal median over the whole injection window (legacy). When
#              the jet is steady it leaks into the median and subtraction clips
#              the bright-side edge ramp (the EDGE_BAND_* walk-out compensates).
# "pre-onset": median over ONLY the jet-free padding frames at the folder start
#              (count from injection_meta.json, written by injection_extract),
#              so the background never contains the jet. Falls back to "window"
#              when the meta file is absent or too few pre-frames exist.
BG_MODE = "pre-onset"        # default: never bake a steady jet into the bg.
                             # A steady jet dominates the whole-window median,
                             # gets subtracted away, fails MIN_PEAK, and the
                             # jet-frame counter then skips the real steady
                             # phase (measured frames land ~100 frames late).
                             # Safe: falls back to "window" without meta.
BG_MIN_PRE_FRAMES = 8        # need at least this many jet-free frames

# Auto-pick measure mode: instead of fixed start..end jet-frame indices,
# scan from the first measurable jet frame and measure the FIRST run of
# AUTO_PICK_COUNT file-consecutive frames where the jet is stable: span
# spread within AUTO_STABLE_TOL of the window median AND angle spread within
# AUTO_STABLE_ANGLE_TOL. The angle check matters: a fast jet reaches full
# span on its first frame, so during the burst the span is already steady
# while the measured angle is still settling. Falls back to the steadiest
# run seen if no window qualifies.
AUTO_PICK_COUNT = 10
AUTO_STABLE_TOL = 0.05
AUTO_STABLE_ANGLE_TOL = 0.5   # deg; max-min angle across the window

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
# Angle policy when a nozzle reference is set: "max" reports the worse edge's
# deviation (legacy -- a badly-fitted edge becomes the number); "trusted"
# reports the trusted edge alone when exactly one edge is Low-confidence.
ANGLE_POLICY = "max"       # "trusted" is part of the opt-in edge-detection V2 set
# Pool the chosen raw edge samples of ALL measured frames into one TLS fit per
# edge (~11x the data; droplet/locus jitter averages out). Reported ALONGSIDE
# the per-frame angles (pooled_angle result key + CSV summary row), never
# replacing them. Pure addition; flag exists only as an emergency off-switch.
POOLED_FIT = True
CONF_HIGH = 75             # score >= this  -> High
CONF_MEDIUM = 50           # score >= this  -> Medium, else Low
CONF_COLORS = {            # BGR text color per confidence level
    "High": (0, 255, 0),
    "Medium": (0, 255, 255),
    "Low": (0, 0, 255),
}


# ---- Edge-detection V2 opt-in ----------------------------------------------
# The three benchmark-gated V2 flags as one switch. Defaults stay legacy until
# the A/B comparison on the rig confirms V2; the GUI's "Edge detection V2"
# checkbox routes each measure run through this context manager.
V2_FLAGS = {"EDGE_MODEL": "erf", "BG_MODE": "pre-onset", "ANGLE_POLICY": "trusted"}


@contextmanager
def edge_v2(enabled=True):
    """Temporarily switch the module to the V2 edge-detection flag set
    (erf edge model + pre-onset background + trusted-edge angle policy),
    restoring the previous flags on exit. No-op when ``enabled`` is False."""
    global EDGE_MODEL, BG_MODE, ANGLE_POLICY
    if not enabled:
        yield
        return
    old = (EDGE_MODEL, BG_MODE, ANGLE_POLICY)
    EDGE_MODEL = V2_FLAGS["EDGE_MODEL"]
    BG_MODE = V2_FLAGS["BG_MODE"]
    ANGLE_POLICY = V2_FLAGS["ANGLE_POLICY"]
    try:
        yield
    finally:
        EDGE_MODEL, BG_MODE, ANGLE_POLICY = old


# ---- I/O -----------------------------------------------------------------
def list_frames(source_dir):
    return injection_extract.list_frames(source_dir)


def load_gray(path):
    """Read a grayscale image (BMP/PNG/TIFF). Fast path for raw 8-bit BMP."""
    info = injection_extract._bmp_info(path)
    if info is not None and info[3] == 8:
        offset, width, height, _, bottom_up = info
        data = np.fromfile(path, dtype=np.uint8)
        if data.size >= offset + width * height:
            frame = data[offset : offset + width * height].reshape(height, width)
            return frame[::-1] if bottom_up else frame
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Cannot read image: {path}")
    return img


def compute_background(files, sample=80):
    """Per-pixel temporal median over a sampling of frames (static scene)."""
    idx = np.linspace(0, len(files) - 1, min(sample, len(files))).astype(int)
    stack = np.stack([load_gray(files[i]) for i in idx])
    return np.median(stack, axis=0).astype(np.int16)


def _pre_onset_background(files, source_dir):
    """Median background from the jet-free head of an injection folder, using
    injection_meta.json's pre_frames count. None if unavailable/insufficient."""
    meta_path = Path(source_dir) / "injection_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        pre = int(meta["pre_frames"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if pre < BG_MIN_PRE_FRAMES or pre > len(files):
        return None
    stack = np.stack([load_gray(f) for f in files[:pre]])
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


def _erf_edge(seg, peak, core, is_top):
    """Fit a blurred-step model around the gradient peak of one column side.

    ``seg`` is the column segment (float array), ``peak`` the integer gradient
    peak index within it, ``core`` the bright-core index, ``is_top`` selects the
    ramp orientation (top edge: intensity RISES with row index toward the core;
    bottom edge: falls). Returns ``(subpixel_row_in_seg | None, confidence)``
    where confidence in [0, 1] reflects the residual vs the fitted amplitude.
    """
    lo = max(0, peak - ERF_FIT_HALF)
    hi = min(len(seg) - 1, peak + ERF_FIT_HALF)
    if hi - lo < 4:
        return None, 0.0
    y = np.arange(lo, hi + 1, dtype=float)
    v = np.asarray(seg[lo : hi + 1], dtype=float)
    vmin, vmax = float(v.min()), float(v.max())
    if vmax - vmin < ERF_MIN_AMP:
        return None, 0.0
    sign = 1.0 if is_top else -1.0

    def model(yy, mu, sigma, base, amp):
        return base + amp * 0.5 * (1.0 + _scipy_erf(sign * (yy - mu)
                                                    / (sigma * np.sqrt(2.0))))

    p0 = (float(peak), 1.0, vmin, vmax - vmin)
    bounds = ((lo, 0.3, 0.0, ERF_MIN_AMP), (hi, ERF_SIGMA_MAX, 255.0, 255.0))
    try:
        popt, _ = curve_fit(model, y, v, p0=p0, bounds=bounds, maxfev=200)
    except (RuntimeError, ValueError):
        return None, 0.0
    mu, sigma, base, amp = popt
    resid = float(np.sqrt(np.mean((model(y, *popt) - v) ** 2)))
    conf = float(np.clip(1.0 - resid / max(amp, 1e-6), 0.0, 1.0))
    if conf <= 0.0:
        return None, 0.0
    return float(mu), conf


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

    With ``return_candidates=True`` the return value is ``(xs, top, bot)``
    where ``top``/``bot`` are dicts ``{"grad", "vis", "erf", "conf"}``: the
    gradient locus, the visible-edge crossing locus (see EDGE_VISIBLE_FRAC),
    the erf blurred-step locus with its per-column confidence (both None
    unless ``EDGE_MODEL == "erf"``) -- so the caller can pick the straightest
    candidate per edge. The default 3-tuple returns the gradient locus only.
    """
    h = gray.shape[0]
    col_smooth = gaussian_filter1d(gray.astype(np.float64), smooth, axis=0)
    want_vis = return_candidates and EDGE_VISIBLE_FRAC is not None
    want_erf = return_candidates and EDGE_MODEL == "erf"
    xs, y_top, y_bot, y_top_v, y_bot_v = [], [], [], [], []
    y_top_e, y_bot_e, conf_top, conf_bot = [], [], [], []
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
        if want_erf:
            # Fit on the RAW column, not the smoothed one -- the model handles
            # noise, and smoothing would inflate the fitted sigma.
            raw_seg = gray[r0 : r1 + 1, x].astype(np.float64)
            te, tc = _erf_edge(raw_seg, it, core, True) if core >= 1 else (None, 0.0)
            be, bc = _erf_edge(raw_seg, ib, core, False) \
                if core < seg.size - 1 else (None, 0.0)
            y_top_e.append(float(r0 + te) if te is not None else float(top))
            conf_top.append(tc)
            y_bot_e.append(float(r0 + be) if be is not None else float(bot))
            conf_bot.append(bc)
    xs = np.array(xs)
    y_top, y_bot = np.array(y_top), np.array(y_bot)
    if not return_candidates:
        return xs, y_top, y_bot
    top = {"grad": y_top,
           "vis": np.array(y_top_v) if want_vis else y_top.copy(),
           "erf": np.array(y_top_e) if want_erf else None,
           "conf": np.array(conf_top) if want_erf else None}
    bot = {"grad": y_bot,
           "vis": np.array(y_bot_v) if want_vis else y_bot.copy(),
           "erf": np.array(y_bot_e) if want_erf else None,
           "conf": np.array(conf_bot) if want_erf else None}
    return xs, top, bot


def _pick_best_locus(xr, cands):
    """Choose the straightest candidate locus for one edge.

    ``cands`` is a list of (name, roi_points, full_array); straightness is the
    robust sigma around each candidate's own least-squares line (as in
    _pick_edge_locus). Later entries win ties within EDGE_PICK_TOL, so order
    candidates from most conservative to most preferred: grad, vis, erf.
    Returns (name, full_array).
    """
    if xr.size < 2:
        return cands[0][0], cands[0][2]

    def sig(y):
        k, b = np.polyfit(xr, y, 1)
        return _robust_sigma(y - (k * xr + b))

    best_name, best_full, best_sig = cands[0][0], cands[0][2], sig(cands[0][1])
    for name, roi_pts, full in cands[1:]:
        s = sig(roi_pts)
        if s <= EDGE_PICK_TOL * best_sig:
            best_name, best_full, best_sig = name, full, min(s, best_sig)
    return best_name, best_full


def _pick_edge_locus(xr, grad_roi, vis_roi, tol=EDGE_PICK_TOL):
    """Choose gradient vs visible-edge points for one edge: the straighter wins.

    Superseded by _pick_best_locus (which also handles the erf candidate);
    kept for reference/CLI compatibility.

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


def edge_quality(rms, edge_conf):
    """0-100 score for ONE edge: fit straightness AND estimator confidence."""
    s_fit = _ramp_score(rms, QUALITY_RMS_GOOD, QUALITY_RMS_BAD)
    s_conf = float(np.clip(edge_conf, 0.0, 1.0)) * 100.0
    return min(s_fit, s_conf)


def resolve_angle(angle_upper, angle_lower, conf_upper, conf_lower):
    """Reported angle + policy tag. Under "trusted", when exactly one edge is
    Low-confidence the other edge's deviation is reported alone."""
    if ANGLE_POLICY == "trusted":
        if conf_upper != "Low" and conf_lower == "Low":
            return angle_upper, "upper-only"
        if conf_lower != "Low" and conf_upper == "Low":
            return angle_lower, "lower-only"
    return max(angle_upper, angle_lower), "max"


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

    # Per-edge locus selection among the candidates (gradient peak, visible
    # crossing, and -- in erf mode -- the blurred-step fit): straightest wins,
    # later candidates preferred on ties (EDGE_PICK_TOL).
    def _cands(c):
        lst = [("grad", c["grad"][roi], c["grad"]),
               ("vis", c["vis"][roi], c["vis"])]
        if c["erf"] is not None:
            lst.append(("erf", c["erf"][roi], c["erf"]))
        return lst

    top_name, y_top = _pick_best_locus(xr.astype(float), _cands(top_cands))
    bot_name, y_bot = _pick_best_locus(xr.astype(float), _cands(bot_cands))

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
        "raw_roi": (xr.astype(float), y_top[roi].astype(float),
                    y_bot[roi].astype(float)),
        "edge_conf_upper": float(np.mean(top_cands["conf"][roi]))
                           if top_cands["conf"] is not None else 1.0,
        "edge_conf_lower": float(np.mean(bot_cands["conf"][roi]))
                           if bot_cands["conf"] is not None else 1.0,
        "locus_upper": top_name,
        "locus_lower": bot_name,
    }


def jet_in_rect(result, rect):
    """True when BOTH fitted edge lines stay inside the reference rectangle
    over the rectangle's x-window. Lines are straight, so checking the two
    x endpoints suffices; uses the stored axis-aligned bbox ``rect``
    (same window `_clip_lines_to_x` draws to)."""
    x0, y0, x1, y1 = rect
    x_lo, x_hi = min(x0, x1), max(x0, x1)
    y_lo, y_hi = min(y0, y1), max(y0, y1)
    for p0, kname in (("up0", "k_upper"), ("lo0", "k_lower")):
        k = float(result[kname])
        b = float(result[p0][1]) - k * float(result[p0][0])
        for x in (x_lo, x_hi):
            if not (y_lo <= k * x + b <= y_hi):
                return False
    return True


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
def _window_spread_ok(window, tol=AUTO_STABLE_TOL, angles=None,
                      angle_tol=AUTO_STABLE_ANGLE_TOL):
    """True if every span in *window* is measurable (not None), the span
    spread (max - min) is within *tol* of the window median, and -- when
    *angles* is given -- the angle spread is within *angle_tol* degrees."""
    if any(s is None for s in window):
        return False
    med = float(np.median(window))
    if med <= 0 or (max(window) - min(window)) > tol * med:
        return False
    if angles is not None:
        if any(a is None for a in angles):
            return False
        if max(angles) - min(angles) > angle_tol:
            return False
    return True


def find_stable_window(spans, angles=None, count=AUTO_PICK_COUNT,
                       tol=AUTO_STABLE_TOL, angle_tol=AUTO_STABLE_ANGLE_TOL):
    """Index of the FIRST run of *count* consecutive stable frames, else None.

    *spans* (and optionally *angles*) hold one entry per frame in folder
    order: the measured value, or None for a frame with no measurable jet
    (breaks the run).
    """
    for i in range(count, len(spans) + 1):
        a = angles[i - count:i] if angles is not None else None
        if _window_spread_ok(spans[i - count:i], tol, a, angle_tol):
            return i - count
    return None


def measure_folder(source_dir, dest_base=None, start=MEASURE_START, end=MEASURE_END,
                   start_x=None, end_x=None, line_frac=None, progress=None,
                   auto_pick=False, ref_lines=True):
    """Measure jet frames ``start`` .. ``end`` (1-based, from the first frame
    that has a jet) and save annotated images + a CSV report.

    With ``auto_pick=True`` the ``start``/``end`` indices are ignored: the scan
    walks forward from the first measurable jet frame and measures the FIRST
    run of ``AUTO_PICK_COUNT`` file-consecutive frames whose jet span is
    stable (``find_stable_window``) -- the settled jet right after the burst.
    If no window qualifies, the steadiest run seen is used instead
    (``auto_pick_fallback`` is set in the result).
    """
    source_dir = Path(source_dir)
    files = list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")
    start = max(1, start)
    end = max(start, end)

    bg = None
    bg_source = "window"
    if BG_MODE == "pre-onset":
        bg = _pre_onset_background(files, source_dir)
        if bg is not None:
            bg_source = "pre-onset"
    if bg is None:
        bg = compute_background(files)

    if dest_base is None:
        parents = source_dir.parents
        base = parents[1] if len(parents) > 1 else source_dir.parent
        dest_base = base / DEST_FOLDER_NAME
    dest_dir = injection_extract.make_dest_dir(source_dir, dest_base)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: measure. Annotation happens after, because the span-ratio quality
    # metric needs the longest jet in the run as its reference.
    measured = []
    auto_fallback = False
    if auto_pick:
        # Walk from the first measurable jet frame; stop at the first run of
        # AUTO_PICK_COUNT file-consecutive frames with a stable jet (span AND
        # angle -- span alone stays steady even during the burst).
        spans = []
        angles_seen = []
        recent = []                       # last frames of the current run
        best = None                       # (instability, entries) fallback
        for path in files:
            gray = load_gray(path)
            result = measure_frame(gray, bg, start_x=start_x, end_x=end_x,
                                   line_frac=line_frac)
            if result is None:
                spans.append(None)
                angles_seen.append(None)
                recent = []
            else:
                spans.append(result["jet_span"])
                angles_seen.append(result["angle"])
                recent.append((path.name, gray, result))
                if len(recent) > AUTO_PICK_COUNT:
                    recent.pop(0)
                if len(recent) == AUTO_PICK_COUNT:
                    window = spans[-AUTO_PICK_COUNT:]
                    win_angles = angles_seen[-AUTO_PICK_COUNT:]
                    if _window_spread_ok(window, angles=win_angles):
                        measured = list(recent)
                        break
                    # Fallback ranking: combined relative span spread +
                    # angle spread (in units of their tolerances).
                    med = float(np.median(window))
                    rel = ((max(window) - min(window)) / (med * AUTO_STABLE_TOL)
                           if med > 0 else float("inf"))
                    rel += (max(win_angles) - min(win_angles)) / AUTO_STABLE_ANGLE_TOL
                    if best is None or rel < best[0]:
                        best = (rel, list(recent))
            if progress is not None:
                progress(len(spans), len(files))
        if not measured and best is not None:
            measured = best[1]            # steadiest run seen
            auto_fallback = True
        target = AUTO_PICK_COUNT
    else:
        target = end - start + 1
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
        q_up = edge_quality(r["rms_upper"], r.get("edge_conf_upper", 1.0))
        q_lo = edge_quality(r["rms_lower"], r.get("edge_conf_lower", 1.0))
        r["quality_upper"], r["quality_lower"] = q_up, q_lo
        r["confidence_upper"] = confidence_level(q_up)
        r["confidence_lower"] = confidence_level(q_lo)
        r["angle_policy"] = "max"
        has_ref = ref and ref.get("image_size") == [gray.shape[1], gray.shape[0]]
        # Angle vs. the blue centerline: the deviation of each green edge from the
        # spray axis. Report the larger of the two half-angles (the worst edge) --
        # or, under ANGLE_POLICY="trusted", the trusted edge alone when exactly
        # one edge is Low-confidence.
        if has_ref and blue_dir is not None:
            r["angle_upper"] = line_angle_deg(blue_dir, r["dir_upper"])
            r["angle_lower"] = line_angle_deg(blue_dir, r["dir_lower"])
            r["angle"], r["angle_policy"] = resolve_angle(
                r["angle_upper"], r["angle_lower"],
                r["confidence_upper"], r["confidence_lower"])
        # Jet-vs-rectangle verdict (before the clip, though the clip preserves
        # the line equations): both green edges inside the red rect => OK.
        r["in_rect"] = ""
        if has_ref and ref.get("rect"):
            r["in_rect"] = "OK" if jet_in_rect(r, ref["rect"]) else "NG"
            rx0, _, rx1, _ = ref["rect"]
            _clip_lines_to_x(r, min(rx0, rx1), max(rx0, rx1))
        draw_scale = MEASURE_RENDER_SCALE * MEASURE_LINE_SS
        annotated = annotate(gray, r, scale=draw_scale)
        if has_ref:
            reference_lines.draw_reference(annotated, ref, scale=draw_scale,
                                           lines=ref_lines)
        if MEASURE_LINE_SS != 1:            # downscale to output size -> thinner lines
            out_w = gray.shape[1] * MEASURE_RENDER_SCALE
            out_h = gray.shape[0] * MEASURE_RENDER_SCALE
            annotated = cv2.resize(annotated, (out_w, out_h), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(dest_dir / name), annotated)

    angles = [r["angle"] for _, _, r in measured]
    angle_std = float(np.std(angles, ddof=1)) if len(angles) > 1 else 0.0
    # Pooled fit: one TLS line per edge over every measured frame's chosen raw
    # edge samples (the same steady jet), reported alongside the per-frame mean.
    pooled_angle, pooled_n = float("nan"), 0
    if POOLED_FIT:
        px = np.concatenate([r["raw_roi"][0] for _, _, r in measured])
        pu = np.concatenate([r["raw_roi"][1] for _, _, r in measured])
        pl = np.concatenate([r["raw_roi"][2] for _, _, r in measured])
        if px.size >= MIN_POINTS:
            k_u, b_u, _, vx_u, vy_u = tls_fit(px, pu)
            k_l, b_l, _, vx_l, vy_l = tls_fit(px, pl)
            if blue_dir is not None:
                pooled_angle = max(line_angle_deg(blue_dir, (vx_u, vy_u)),
                                   line_angle_deg(blue_dir, (vx_l, vy_l)))
            else:
                pooled_angle = spray_angle(k_u, k_l)
            pooled_n = int(px.size)
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
                 "rms_up_px,rms_lo_px,coverage,span_ratio,quality,confidence,"
                 "q_up,q_lo,policy,in_rect\n")
        for name, _, r in measured:
            fh.write(f"{name},{r['angle']:.2f},{r['k_upper']:.5f},"
                     f"{r['k_lower']:.5f},{r['n_points']},"
                     f"{r['rms_upper']:.3f},{r['rms_lower']:.3f},"
                     f"{r['coverage']:.3f},{r['span_ratio']:.3f},"
                     f"{r['quality']:.0f},{r['confidence']},"
                     f"{r['quality_upper']:.0f},{r['quality_lower']:.0f},"
                     f"{r['angle_policy']},{r['in_rect']}\n")
        fh.write(f"mean,{np.mean(angles):.2f},,,,,,,,,,,,\n")
        fh.write(f"std,{angle_std:.3f},,,,,,,,,,,,\n")
        fh.write(f"trusted_mean,{trusted_mean:.2f},,,{len(trusted)},,,,,,,,,"
                 f"excl. Low frames\n")
        fh.write(f"pooled_angle,{pooled_angle:.2f},,,{pooled_n},,,,,,,,,"
                 f"all-frame fit\n")
        fh.write(f"run_confidence,{run_conf} ({run_score:.0f}),,,,,,,,,,,,\n")

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
        "pooled_angle": pooled_angle,
        "pooled_n": pooled_n,
        "edge_model": EDGE_MODEL,
        "bg_mode": bg_source,   # the background actually used (pre-onset
                                # silently falls back to window without meta)
        "angle_policy_mode": ANGLE_POLICY,
        "auto_pick": bool(auto_pick),
        "auto_pick_fallback": auto_fallback,
        "run_quality": run_score,
        "confidence": run_conf,
        "frames": [(name, r["angle"]) for name, _, r in measured],
        "frame_confidence": [
            (name, r["quality"], r["confidence"]) for name, _, r in measured
        ],
        "frame_in_rect": [(name, r["in_rect"]) for name, _, r in measured],
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
