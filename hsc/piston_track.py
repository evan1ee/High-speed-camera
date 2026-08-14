#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Track the nozzle piston's left edge through a high-speed burst.

The needle-free injector's piston is driven horizontally down the barrel while
the dose is expelled (~50-250 ms, depending on dose). Filmed from the side it
is a **dark body on a bright barrel interior** -- the inverse of the water jet
that :mod:`hsc.measure_angle` measures -- so it needs its own edge detector,
though the line fitting (RANSAC -> Total Least Squares) is shared with it.

Pipeline
--------
1. :func:`build_profile` -- once per run. A temporal max/min over sampled
   frames separates the bright barrel interior from the dark walls (and from
   the holder / rod clutter outside it), giving the row band to search and the
   dark/bright levels that set the edge threshold. Per-run levels are used
   rather than per-frame Otsu because the piston's share of the frame changes
   as it travels, which would drag a per-frame threshold with it.
2. :func:`measure_frame_edge` -- per frame. Along every row of the band, walk
   from the left to the first bright->dark step that starts a dark run of at
   least ``MIN_DARK_RUN`` px (mist streaks and residue are shorter, and would
   otherwise put the edge tens of px early), refine it to sub-pixel by the
   parabolic vertex of the intensity gradient, then fit the near-vertical
   locus with RANSAC -> TLS as ``x = k*y + b``.
3. :func:`track` / :func:`detect_piston_bounds` -- the per-frame position
   series, and the injection window derived directly from it: the stroke
   starts when the position leaves its pre-injection baseline by more than the
   noise floor, and ends at the first sustained plateau. Deriving the window
   from the physical displacement (rather than from the jet's temporal-motion
   signal) keeps mist and spray turbulence out of the decision.

Camera-free and Tk-free, so it is unit-testable headless.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import binary_closing, gaussian_filter1d

from hsc import injection_extract
from hsc import measure_angle as ma


# ---- Barrel band ---------------------------------------------------------
PROFILE_SAMPLE = 60        # frames sampled for the temporal max/min images
BAND_BRIGHT_FRACS = (0.5, 0.35, 0.2)   # tried in order: bright px per row
BAND_INSET_FRAC = 0.12     # shrink the band away from the wall gradients
MIN_BAND_ROWS = 8
#: The barrel is taller than the piston, so "bright rows" alone leaves rows
#: that never contain the piston (on the rig, band 60..215 while the piston
#: spans 72..170) -- they contribute edges from the holder and splash, which
#: can out-vote the real ones. A row is kept only if the temporal MIN image
#: shows a dark run at least this fraction of the longest one, i.e. the piston
#: swept through it at some point during the run.
BAND_BODY_FRAC = 0.5
DARK_PCT, BRIGHT_PCT = 10, 90          # percentiles of the min / max images
MIN_CONTRAST = 25.0        # bright - dark below this: not a usable barrel view

# ---- Edge ----------------------------------------------------------------
#: The piston body is the LONGEST dark run in a row, not the first one. Once
#: the stroke starts, small dark artefacts appear to the left of it -- a seal
#: at the barrel end, splash, bubbles -- and "first run" locks onto those and
#: reports a few px of wobble instead of the real travel (measured on the rig
#: 2026-08-07: at frame 3540 the runs were (23,8) (39,9) (64,151), the piston
#: being the 151 px one). Body vs artefact separates by an order of magnitude,
#: so the longest run is unambiguous; this floor only rejects a frame with no
#: piston left in view at all.
#: The edge is the left end of the first run of ``MIN_BODY_RUN`` consecutive
#: pixels darker than ``BODY_DARK_FRAC`` of the way from the run's dark level
#: to its bright level -- i.e. genuinely black, not merely dark.
#:
#: The scene is full of impostors, and neither position, width nor
#: connectivity separates them from the piston: a static seal sits at x~24, and
#: the piston's own collar leaves a stripe that is 3 px behind the body at rest
#: but 20 px behind it mid-stroke, touching in some rows and detached in
#: others. Brightness does separate them cleanly, and by a wide margin -- on
#: rig run 2026-08-07 the seal reaches 41-62, the collar 34-55, while the body
#: is 3-15 everywhere. Requiring real blackness AND real width picks the body
#: face in every row of every frame, which is the edge the operator marks.
MIN_BODY_RUN = 30          # px: narrowest black run accepted as the piston body
#: ... unless the run is cut off by the right frame border, in which case only
#: this much is required: a clipped body is not a narrow impostor, it is a
#: partial view of the real one. Without this the piston stops being detected
#: as it leaves the frame -- on run 2026-08-07-17-41-15 the last 27 frames of
#: the stroke were lost that way, while the face itself was still visible.
MIN_BORDER_RUN = 8
BODY_DARK_FRAC = 0.08      # of (bright - dark) above the dark level

#: SHORT ROIs GET THEIR OWN EDGE DEFINITION -- deliberately not the taller
#: ROIs' rule. A 320x64 frame is a crop INTO the barrel (48 usable rows against
#: 79 at both 320x120 and 320x240), and the piston in it is GREY, not black:
#: 28-38 against a barrel at 253 on rig run 2026-08-13-09-31-20. The blackness
#: rule cannot work there -- the body straddles its own threshold, so the first
#: run of "genuinely black" pixels begins ~35 px INSIDE the piston.
#:
#: Short frames instead take the VISIBLE edge: the first sustained departure
#: from the bright barrel, which is the boundary the operator marks.
#:
#: The fraction has to be well BELOW the midpoint, and the reason is the collar
#: again. Mid-stroke a row reads 253 .. 144 130 124 114 116 140 159 .. 87 61 49
#: 40 35: a ~10 px collar dip, a recovery, then the body. A shallow threshold
#: (0.25 -> 193) swallows dip and body as one run and reports the edge ~10 px
#: early; 0.55 -> 120 leaves the dip too short to satisfy MIN_BODY_RUN, so it
#: is rejected and the edge lands on the body. Verified against hand-marked
#: frames across the stroke of run 2026-08-13-09-31-20, at rest and moving.
#: The taller ROIs keep the blackness rule untouched.
#: It takes TWO stages, because no single threshold works in both scene
#: states. At rest the collar sits against the body; mid-stroke it detaches,
#: leaving a ~10 px dip and a recovery between it and the body. Measured:
#:   walk threshold 193 -> rest 118 (right), mid-stroke 181 (want 190)
#:   walk threshold 120 -> rest 122 (right), mid-stroke 190 (right)
#: So: locate the body with a DARK threshold it always satisfies (the body is
#: 26-40 against a collar at 114-160), then walk LEFT to the visible crossing.
#: The recovery between collar and body stops that walk, which is exactly what
#: a single threshold cannot do -- shallow enough to reach the visible edge is
#: also shallow enough to cross the collar.
SHORT_ROI_ROWS = 80
SHORT_BODY_FRAC = 0.75     # of (bright - dark) below bright: locates the body
VISIBLE_EDGE_FRAC = 0.55   # of (bright - dark) below bright: the visible edge
SHORT_MAX_WALK = 25        # px; bound on the walk out to the visible edge
MIN_DARK_RUN = 12          # px: legacy floor, still applied to the row length
#: Bright gaps up to ``GAP_CLOSE - 1`` px wide are closed before the runs are
#: measured. The piston's left edge carries a narrow rim with a bright
#: reflective sliver behind it, which splits the body in some rows but not
#: others -- e.g. row 108 reads (14,8) (25,152) while row 156 reads (13,131).
#: Unclosed, those are two rival clusters and the RANSAC fit flips between
#: them from frame to frame, which looked like +/-14 px of baseline noise
#: (rig data 2026-08-07). Closing merges them so the edge is always the OUTER
#: one, which is what the operator's reference images mark. Kept well below
#: the gap to the seal artefact (>= 8 px) so that stays a separate run.
#: Closing is DISABLED (1). It was added to attach the collar stripe to the
#: body, but the stripe separates from the body as the stroke proceeds, and
#: any closing wide enough to bridge the gap at rest also bridges it in about
#: half the rows mid-stroke and not the other half -- which is precisely the
#: ~20 px row-to-row disagreement that put the line on the stripe instead of
#: the body face. Requiring MIN_BODY_RUN consecutive *genuinely* dark pixels
#: needs no bridging: the body qualifies, the stripe never does.
GAP_CLOSE = 1
EDGE_SMOOTH = 1.0          # Gaussian sigma along the row before the gradient
GRAD_SEARCH = 4            # px around the run start to look for the steepest ramp
RANSAC_RESIDUAL = 1.5      # px inlier tolerance for the near-vertical edge fit
MIN_EDGE_POINTS = 6
#: Rows whose edge sits within this many px of the frame's median edge are
#: taken to be part of the piston's flat face. Mid-stroke the silhouette is a
#: staircase -- on the rig at frame 3540 the face sat at x=40 with the crown
#: above it at 65 and a trailing skirt below at 22 -- and a band spanning all
#: three lets the RANSAC fit jump between them as their row counts change.
#: refine_band keeps only the run of rows that agree across the stroke.
AGREE_TOL = 2.0
AGREE_SAMPLE = 24          # frames sampled to score row agreement

# ---- Stroke detection ----------------------------------------------------
BASELINE_FRAMES = 20       # head frames defining the "piston at rest" position
MOVE_ABS_PX = 0.6          # displacement floor to call the piston moving
MOVE_SIGMA_K = 5.0         # ... or this many robust sigmas, whichever is larger
#: ... or this fraction of the stroke actually observed, whichever is largest.
#: The head-frame sigma alone is far too optimistic: on the rig the resting
#: position is quiet over 20 frames but wanders ~2 px over thousands, which
#: tripped a 0.6 px threshold 2700 frames before the real stroke. Anchoring
#: the floor to the travel that is actually present makes it scale-free.
MOVE_TRAVEL_FRAC = 0.05
MOVE_CONFIRM = 3           # frames the motion must persist (rejects a spike)
MAX_ONSET_WALK = 200       # frames; bound on the walk back to the true onset
#: The walk back to the onset asks "is the piston moving HERE?" using the
#: local frame-to-frame step, not "is it far from where it started?" using the
#: displacement from the head baseline. Over thousands of frames the barrel
#: drifts further than any sane displacement floor, so that test never sees
#: "at rest" and the walk runs back to MAX_ONSET_WALK -- on rig run
#: 2026-08-12-14-07-22 it stopped 194 frames early, padding the copied window
#: with 185 ms of resting frames. The local step separates the two states by
#: an order of magnitude: measured on that run, 0.02 px median at rest
#: (0.30 px worst case) against 1.73 px mid-stroke.
ONSET_SPEED_FRAC = 0.25    # of the stroke's typical step
ONSET_STEP_FLOOR = 0.35    # px; floor for the "still" test, above rest noise
ONSET_QUIET = 5            # consecutive still frames that end the walk
ONSET_STEP_SAMPLE = 50     # frames after the trigger defining the stroke step
#: Plateau tolerance as a fraction of the travel the stroke itself would cover
#: across HOLD_FRAMES. Frame-rate independent, unlike a fixed displacement.
PLATEAU_STEP_FRAC = 0.25
#: A step larger than this between consecutive frames is not motion -- at
#: ~1000 fps and ~0.06 mm/px it would be over 600 mm/s, far beyond what the
#: piston does. It means the detector changed its mind about which part of
#: the silhouette is the edge, which happens during the first few ms of the
#: stroke while the scene reorganises. Such frames are flagged so they cannot
#: masquerade as a speed peak.
MAX_STEP_PX = 10.0
MEDIAN_WINDOW = 5          # frames; kills single-frame position spikes
HOLD_FRAMES = 15           # quiet frames that confirm the stroke has ended
#: What separates "no injection in this burst" from a real one, for
#: locate_stroke. Both tests are DOSE-INDEPENDENT: the stroke is proportional
#: to the dose, so any floor in frames or pixels is really a floor on the dose.
#: The first version used 20 frames / 15 px, read off the 40 U runs that
#: existed then, and rejected a good 4 U injection -- 19 frames, 20.3 px, which
#: converts back to 0.044 mL = 4.4 U, exactly its label.
MIN_STROKE_MS = 2.0        # rejects one- and two-frame artefacts
MIN_TRAVEL_SIGMA = 6.0     # travel must exceed the resting noise by this much
MIN_TRAVEL_PX = 3.0        # ... and this, if the baseline is unusually quiet
#: locate_stroke only (see its docstring for why it cannot share these with
#: detect_piston_bounds).
TRIGGER_WINDOW = 30        # frames in the local baseline
SETTLE_SAMPLE = 300        # frames after the plateau defining the parked level
#: Below this share of frames yielding an edge, the burst has a contrast
#: problem (usually over-exposure), not a stroke problem. Good rig runs detect
#: 90%+; the frames that legitimately miss are the tail, after the piston has
#: left the view.
MIN_DETECT_FRAC = 0.6

META_NAME = "piston_meta.json"          # written into the injection folder
CAPTURE_META_NAME = "piston_capture.json"   # written into the burst folder


@dataclass(frozen=True, eq=False)
class BarrelProfile:
    """Where to look for the piston edge, and what counts as dark."""

    row_lo: int
    row_hi: int             # inclusive
    dark: float
    bright: float
    #: True for a short ROI (see SHORT_ROI_ROWS), which uses the visible-edge
    #: rule instead of the blackness rule.
    short: bool = False

    @property
    def thresh(self):
        return 0.5 * (self.dark + self.bright)

    @property
    def body_thresh(self):
        """Only the piston's solid body is this black (see MIN_BODY_RUN)."""
        return self.dark + BODY_DARK_FRAC * (self.bright - self.dark)

    @property
    def visible_thresh(self):
        """Where the bright barrel first darkens (short ROIs only)."""
        return self.bright - VISIBLE_EDGE_FRAC * (self.bright - self.dark)

    @property
    def short_body_thresh(self):
        """Dark enough that only the piston body reaches it (short ROIs)."""
        return self.bright - SHORT_BODY_FRAC * (self.bright - self.dark)

    @property
    def edge_thresh(self):
        """The threshold that LOCATES the piston for this ROI.

        Tall ROIs keep the blackness rule exactly as it was. Short ones locate
        the body with their own darker threshold and then walk out to
        ``visible_thresh`` -- see SHORT_ROI_ROWS for why one threshold cannot
        do both jobs.
        """
        return self.short_body_thresh if self.short else self.body_thresh

    @property
    def centre_row(self):
        return 0.5 * (self.row_lo + self.row_hi)

    @property
    def n_rows(self):
        return self.row_hi - self.row_lo + 1

    def as_dict(self):
        return {
            "row_lo": int(self.row_lo), "row_hi": int(self.row_hi),
            "dark": float(self.dark), "bright": float(self.bright),
            "thresh": float(self.thresh),
        }


def _as_gray(frame):
    """Accept either an image path or an already-loaded 2-D array."""
    if isinstance(frame, np.ndarray):
        return frame
    return ma.load_gray(frame)


def _longest_run(flags):
    """Longest run of True in a 1-D boolean array as ``(lo, hi)`` inclusive."""
    best = best_len = None
    run_start = None
    for i, on in enumerate(flags):
        if on and run_start is None:
            run_start = i
        elif not on and run_start is not None:
            if best_len is None or i - run_start > best_len:
                best, best_len = (run_start, i - 1), i - run_start
            run_start = None
    if run_start is not None:
        length = len(flags) - run_start
        if best_len is None or length > best_len:
            best, best_len = (run_start, len(flags) - 1), length
    return best


def _run_length_from(dark):
    """Length of the dark run STARTING at each column (vectorised, per row)."""
    columns = np.arange(dark.shape[1])
    reversed_dark = dark[:, ::-1]
    last_bright = np.maximum.accumulate(
        np.where(reversed_dark, -1, columns[None, :]), axis=1)
    return (columns[None, :] - last_bright)[:, ::-1]


def _longest_true_run_per_row(flags):
    """Length of the longest True run in each row of a 2-D mask (vectorised)."""
    columns = np.arange(flags.shape[1])
    last_false = np.maximum.accumulate(
        np.where(flags, -1, columns[None, :]), axis=1)
    return (columns[None, :] - last_false).max(axis=1)


def _longest_dark_run_per_row(image, threshold):
    """Length of the longest run below *threshold* in each row (vectorised)."""
    return _longest_true_run_per_row(image < threshold)


def _restrict_to_body(lo_img, run, hi_img):
    """Narrow the bright-row band to the rows the piston actually sweeps.

    A row the piston swept is dark in the temporal MIN image (it was there at
    some point) AND bright in the temporal MAX image (it left again). Both
    halves are needed: the holder and the rod are dark in the MIN image too,
    and testing MIN alone hands them the band whenever the piston barely
    moves -- on rig burst 2026-08-11-15-49-22, where the stroke had already
    finished before the capture, that put the band on rows 4..31, the rod at
    the top of the frame, and every green line with it. A static object is
    dark in the MAX image as well, so requiring it to have VACATED excludes
    it, and a run with no sweep at all now falls back to the barrel band.
    """
    lo, hi = run
    band = slice(lo, hi + 1)
    threshold = 0.5 * (float(np.percentile(lo_img[band], DARK_PCT))
                       + float(np.percentile(hi_img[band], BRIGHT_PCT)))
    swept = (lo_img[band] < threshold) & (hi_img[band] >= threshold)
    lengths = _longest_true_run_per_row(swept)
    if lengths.max() < MIN_BODY_RUN:
        return run
    keep = _longest_run(lengths >= BAND_BODY_FRAC * lengths.max())
    if keep is None or keep[1] - keep[0] + 1 < MIN_BAND_ROWS:
        return run
    return lo + keep[0], lo + keep[1]


def build_profile(frames, sample=PROFILE_SAMPLE):
    """Barrel band + dark/bright levels from a sampling of the run.

    The temporal MAX image is bright wherever the barrel interior is ever
    empty, so its bright rows are the interior; the temporal MIN image is dark
    wherever the piston ever passed, which is where the dark level comes from.
    """
    frames = list(frames)
    if not frames:
        raise RuntimeError("No frames to profile.")
    idx = np.linspace(0, len(frames) - 1, min(sample, len(frames))).astype(int)
    stack = np.stack([_as_gray(frames[i]).astype(np.uint8) for i in np.unique(idx)])
    hi_img = stack.max(axis=0)
    lo_img = stack.min(axis=0)

    _, bright_mask = cv2.threshold(hi_img, 0, 255,
                                   cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright_frac = (bright_mask > 0).mean(axis=1)

    run = None
    for min_frac in BAND_BRIGHT_FRACS:
        run = _longest_run(bright_frac >= min_frac)
        if run is not None and run[1] - run[0] + 1 >= MIN_BAND_ROWS:
            break
        run = None
    if run is None:
        raise RuntimeError(
            "No barrel interior found: no band of bright rows spans the frame. "
            "Check the lighting / that the barrel is in view.")

    lo, hi = _restrict_to_body(lo_img, run, hi_img)

    inset = max(1, int(round(BAND_INSET_FRAC * (hi - lo + 1))))
    lo, hi = lo + inset, hi - inset
    if hi - lo + 1 < MIN_BAND_ROWS:              # too thin to inset: keep it raw
        lo, hi = run

    dark = float(np.percentile(lo_img[lo : hi + 1], DARK_PCT))
    bright = float(np.percentile(hi_img[lo : hi + 1], BRIGHT_PCT))
    if bright - dark < MIN_CONTRAST:
        raise RuntimeError(
            f"Barrel contrast too low ({bright - dark:.0f} grey levels): the "
            "piston cannot be separated from the background.")
    return BarrelProfile(row_lo=int(lo), row_hi=int(hi),
                         dark=dark, bright=bright,
                         short=bool(hi_img.shape[0] <= SHORT_ROI_ROWS))


def _parabolic_offsets(grad, cols):
    """Vectorised sub-sample offsets of the gradient extrema at ``cols``.

    Same parabola-through-three-samples math as
    :func:`hsc.measure_angle._parabolic_vertex_offset` (asserted equal by test),
    applied to one column index per row at once.
    """
    rows = np.arange(grad.shape[0])
    a = grad[rows, cols - 1]
    b = grad[rows, cols]
    c = grad[rows, cols + 1]
    denom = a - 2.0 * b + c
    with np.errstate(divide="ignore", invalid="ignore"):
        offset = 0.5 * (a - c) / denom
    offset[~np.isfinite(offset)] = 0.0
    offset[denom == 0.0] = 0.0
    offset[np.abs(offset) > 0.5] = 0.0
    return offset


def edge_columns(gray, profile, min_dark_run=MIN_DARK_RUN):
    """Sub-pixel column of the piston's left edge for each row of the band.

    The edge is the left end of the leftmost dark run at least
    ``MIN_BODY_RUN`` px wide -- the piston's solid body face, which is what
    the operator marks. Narrow dark features to its left (the collar stripe,
    the seal, splash) are rejected by that width test; the rim at rest stays
    part of the body because ``GAP_CLOSE`` bridges the thin bright sliver
    behind it.

    Returns ``(rows, xs)``; rows where the piston is absent, off the left
    border, or unresolvable are dropped.
    """
    gray = _as_gray(gray)
    band = gray[profile.row_lo : profile.row_hi + 1].astype(np.float64)
    if band.size == 0 or band.shape[1] < min_dark_run + 4:
        return np.empty(0, dtype=int), np.empty(0, dtype=float)
    smooth = gaussian_filter1d(band, EDGE_SMOOTH, axis=1, mode="nearest")
    width = smooth.shape[1]
    rows_idx = np.arange(band.shape[0])

    # First run of MIN_BODY_RUN consecutive genuinely-black px, per row.
    body = smooth < profile.edge_thresh
    if GAP_CLOSE > 1:
        body = binary_closing(body, structure=np.ones((1, GAP_CLOSE), dtype=bool))

    run_from = _run_length_from(body)
    begins = body & ~np.concatenate(
        [np.zeros((body.shape[0], 1), dtype=bool), body[:, :-1]], axis=1)
    columns = np.arange(width)
    clipped = (columns[None, :] + run_from) >= width      # runs off the frame
    wide = begins & ((run_from >= MIN_BODY_RUN)
                     | (clipped & (run_from >= MIN_BORDER_RUN)))
    found = wide.any(axis=1)
    starts = np.argmax(wide, axis=1)
    lengths = np.where(found, run_from[rows_idx, starts], 0)
    starts = np.where(found, starts, -1)
    min_len = min_dark_run

    # The edge must have bright barrel to its left (a run touching the frame
    # border means the piston is already out of view on that side).
    left_ok = np.zeros(band.shape[0], dtype=bool)
    valid = (lengths >= min_len) & (starts >= 1) & (starts < width - 2)
    if valid.any():
        probe = np.clip(starts[valid] - 3, 0, width - 1)
        left_ok[valid] = smooth[rows_idx[valid], probe] > profile.edge_thresh
    keep = valid & left_ok
    if not keep.any():
        return np.empty(0, dtype=int), np.empty(0, dtype=float)

    # Steepest bright->dark ramp within +/- GRAD_SEARCH px of the run start.
    grad = np.gradient(smooth, axis=1)
    kept_rows = rows_idx[keep]
    kept_starts = starts[keep]
    offsets = np.arange(-GRAD_SEARCH, GRAD_SEARCH + 1)
    window = np.clip(kept_starts[:, None] + offsets[None, :], 1, width - 2)
    if profile.short:
        # Two-stage (short ROIs only): the run start is inside the body; walk
        # back out to where the barrel first darkens. See SHORT_ROI_ROWS.
        xs = _walk_to_visible(smooth[kept_rows], kept_starts,
                              profile.visible_thresh)
        return kept_rows + profile.row_lo, xs

    picks = window[np.arange(window.shape[0]),
                   np.argmin(grad[kept_rows[:, None], window], axis=1)]
    sub = _parabolic_offsets(grad[kept_rows], picks)

    xs = picks.astype(float) + sub
    return kept_rows + profile.row_lo, xs


def _walk_to_visible(rows, starts, threshold, max_walk=SHORT_MAX_WALK):
    """Walk left from each body start to where the row crosses *threshold*.

    Sub-pixel by linear interpolation across the crossing. The walk stops at
    the first pixel at or above the threshold, so the bright recovery between
    a detached collar and the body halts it -- which is the whole point.
    """
    xs = np.empty(starts.size, dtype=float)
    for i in range(starts.size):
        line = rows[i]
        col = int(starts[i])
        limit = max(1, col - max_walk)
        while col > limit and line[col - 1] < threshold:
            col -= 1
        above, below = float(line[col - 1]), float(line[col])
        if above >= threshold > below and above != below:
            xs[i] = (col - 1) + (above - threshold) / (above - below)
        else:
            xs[i] = float(col)
    return xs


def refine_band(frames, profile, sample=AGREE_SAMPLE, tol=AGREE_TOL):
    """Narrow *profile*'s band to the rows that track the same rigid edge.

    The piston's silhouette is stepped: a crown above the flat face and a
    trailing skirt below it, each offset by tens of px and each varying in
    height as the stroke proceeds. Scoring every row by how far its edge sits
    from the frame's median edge, across a sample of frames, isolates the run
    of rows that is the face. Returns *profile* unchanged when the result
    would be too thin to fit a line through.

    Call this with the STROKE frames -- at rest every row agrees, so a sample
    dominated by resting frames tells you nothing.
    """
    frames = list(frames)
    if not frames:
        return profile
    idx = np.unique(
        np.linspace(0, len(frames) - 1, min(sample, len(frames))).astype(int))
    spread = [[] for _ in range(profile.n_rows)]
    for i in idx:
        rows, xs = edge_columns(frames[i], profile)
        if rows.size < MIN_EDGE_POINTS:
            continue
        median_x = float(np.median(xs))
        for row, x in zip(rows - profile.row_lo, xs):
            spread[row].append(abs(float(x) - median_x))

    score = np.array([np.median(v) if v else np.inf for v in spread])
    keep = _longest_run(score <= tol)
    if keep is None or keep[1] - keep[0] + 1 < MIN_BAND_ROWS:
        return profile
    return BarrelProfile(row_lo=profile.row_lo + keep[0],
                         row_hi=profile.row_lo + keep[1],
                         dark=profile.dark, bright=profile.bright,
                         short=profile.short)


def measure_frame_edge(gray, profile, residual=RANSAC_RESIDUAL):
    """Fit the piston's left edge in one frame, or ``None`` if it is not found.

    The fitted line is ``x = k*y + b`` (near-vertical, so x is the dependent
    coordinate); ``x`` is its column at the band's centre row.
    """
    rows, xs = edge_columns(gray, profile)
    if rows.size < MIN_EDGE_POINTS:
        return None
    k, b, n_inliers, vx, vy = ma.tls_fit(rows.astype(float), xs, residual)
    residuals = xs - (k * rows + b)
    # Quality is the scatter of the rows the fit actually used: rows that
    # locked onto a different feature are rejected by RANSAC, and including
    # them would report a large rms for a perfectly good line.
    inliers = np.abs(residuals) <= residual
    x_centre = k * profile.centre_row + b
    gray = _as_gray(gray)
    return {
        "k": float(k),
        "b": float(b),
        "x": float(x_centre),
        # Raw samples kept so the run can be re-fitted with a common slope
        # (see apply_common_slope) without re-reading the frame.
        "rows": rows.astype(float),
        "xs": xs,
        "n_points": int(n_inliers),
        "n_rows": int(rows.size),
        "rms": float(ma._robust_sigma(residuals[inliers])),
        "coverage": float(int(inliers.sum()) / profile.n_rows),
        # The stroke ends when the edge reaches the frame border; flagged so
        # the caller can say "measurement clipped" instead of "piston stopped".
        "at_border": bool(x_centre >= gray.shape[1] - GRAD_SEARCH - 2),
        "direction": (float(vy), float(vx)),   # (dx, dy) in image coordinates
    }


def common_slope(fits, min_points=MIN_EDGE_POINTS):
    """One slope for the whole run, pooled over every frame's edge samples.

    The piston is rigid and travels straight down the barrel, so its face has
    a SINGLE tilt for the entire stroke: any frame-to-frame variation in the
    fitted slope is noise, not motion. Each frame's samples are centred on
    their own median (which removes the per-frame offset and leaves only the
    tilt) and fitted together, so every frame contributes to one estimate.
    Returns ``None`` if no frame has enough samples.
    """
    rows, xs = [], []
    for fit in fits:
        if fit is None or fit["n_points"] < min_points:
            continue
        rows.append(fit["rows"])
        xs.append(fit["xs"] - np.median(fit["xs"]))
    if not rows:
        return None
    rows = np.concatenate(rows)
    xs = np.concatenate(xs)
    if rows.size < MIN_EDGE_POINTS:
        return None
    slope, _b, _n, _vx, _vy = ma.tls_fit(rows, xs)
    return float(slope)


def apply_common_slope(fits, slope, profile, residual=RANSAC_RESIDUAL):
    """Re-fit every frame at the given *slope*, leaving only its offset free.

    This is what makes the drawn lines exactly parallel: they then differ by a
    pure translation, which is the only thing the piston actually does. The
    offset is a median over the frame's samples, so it stays robust to rows
    that latched onto something else.
    """
    for fit in fits:
        if fit is None:
            continue
        rows, xs = fit["rows"], fit["xs"]
        intercept = float(np.median(xs - slope * rows))
        residuals = xs - (slope * rows + intercept)
        inliers = np.abs(residuals) <= residual
        fit["k"] = float(slope)
        fit["b"] = intercept
        fit["x"] = float(slope * profile.centre_row + intercept)
        fit["n_points"] = int(inliers.sum())
        fit["rms"] = float(ma._robust_sigma(residuals[inliers]))
        fit["coverage"] = float(int(inliers.sum()) / profile.n_rows)
    return fits


def line_distance(ref, fit, profile):
    """Perpendicular distance (px) from *ref*'s fitted line to *fit*'s.

    Both lines are near-vertical and near-parallel; the distance is measured
    along the REFERENCE line's normal at the band centre row, which stays
    well-defined when the two lines are not exactly parallel. Positive means
    the piston advanced away from the reference (towards the nozzle).
    """
    if ref is None or fit is None:
        return float("nan")
    dx = float(fit["x"]) - float(ref["x"])
    return dx / float(np.hypot(1.0, ref["k"]))


def track(frames, profile=None, progress=None):
    """Per-frame edge fits for a whole run.

    Returns ``{"x", "fits", "profile"}``; ``x`` is a float array of the edge
    column at the band centre row, NaN where no edge was found.
    """
    frames = list(frames)
    if not frames:
        raise RuntimeError("No frames to track.")
    if profile is None:
        profile = build_profile(frames)

    n = len(frames)
    xs = np.full(n, np.nan, dtype=float)
    fits = [None] * n
    for i, frame in enumerate(frames):
        fit = measure_frame_edge(frame, profile)
        if fit is not None:
            fits[i] = fit
            xs[i] = fit["x"]
        if progress is not None:
            progress(i + 1, n)
    return {"x": xs, "fits": fits, "profile": profile}


#: Parallel file readers for the V2 scan. A burst folder is thousands of small
#: files and a COLD read is seek-bound, not bandwidth- or CPU-bound: measured
#: on this rig at 20.55 ms/file read one at a time versus 1.72 ms/file across
#: 8 threads (12x). 16 threads was slower than 8, so this is the sweet spot.
SCAN_WORKERS = 8
SCAN_CHUNK = 64
#: Coarse pass: look at every Nth frame to bracket the stroke, then measure
#: only that bracket densely. A real stroke runs 90-200 frames, so it lands on
#: 11+ coarse samples at stride 8 -- unmissable -- while the thousands of
#: resting frames either side are never read. This beats what a C++ rewrite of
#: the per-frame work could achieve (measured: 0.54 s coarse-to-fine vs 2.99 s
#: scanning everything, of which only 2.20 s is work a faster language could
#: touch at all), for none of the cost of a second copy of the detector.
SCAN_STRIDE = 8
COARSE_MARGIN = 4          # coarse samples of slack either side of the bracket
COARSE_STEP_FRAC = 0.10    # of the largest coarse step; below this is not motion
COARSE_MIN_FRAMES = 400    # shorter runs are just scanned in full
COARSE_DENSE_GUESS = 300   # progress-bar estimate for the dense pass


def _scan_indices(files, indices, profile, workers, out, progress=None,
                  done=0, total=None, scanned=None):
    """Measure the given frame indices in parallel, writing into *out*.

    *scanned*, when given, is marked True at every index actually looked at --
    the coarse-to-fine scan leaves most frames NaN because it never reads them,
    which is not the same as failing to find an edge in them.
    """
    indices = list(indices)
    if not indices:
        return done
    total = total or len(indices)

    def position(i):
        _rows, xs = edge_columns(_as_gray(files[i]), profile)
        if xs.size < MIN_EDGE_POINTS:
            return i, np.nan
        return i, float(np.median(xs))

    step = max(1, total // 100)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, value in pool.map(position, indices, chunksize=SCAN_CHUNK):
            out[i] = value
            if scanned is not None:
                scanned[i] = True
            done += 1
            if progress is not None and (done % step == 0 or done == total):
                progress(min(done, total), total)
    return done


def scan_positions(files, profile, workers=SCAN_WORKERS, progress=None,
                   stride=SCAN_STRIDE, scanned=None):
    """Edge position per frame -- the fast path, coarse to fine.

    Three things make this ~30x faster than :func:`track` on a full burst,
    none of which costs accuracy where it matters:

    * **Most frames are never looked at.** The piston rests for thousands of
      frames and strokes for 90-200, so a pass at every ``stride``-th frame
      brackets the motion, and only that bracket (plus the head, which sets
      the rest baseline) is then measured densely. Measured on a 4201-frame
      burst: 2.99 s scanning everything, 0.54 s coarse-to-fine.
    * Frames are read **in parallel** (see SCAN_WORKERS) -- a cold burst
      folder is seek-bound, 22 ms/file serially against 1.1 ms across 8 threads.
    * The position is the **median of the per-row edge columns** rather than a
      RANSAC->TLS fit, which costs 2.7 ms/frame and buys nothing here: the
      window is decided by ~1 px thresholds, and every reported number is
      re-measured by :mod:`hsc.measure_piston` on the copied window with the
      full fit.

    Frames that were not measured stay NaN -- honest about what was looked at.
    ``detect_piston_bounds`` interpolates them, which is exact over the resting
    stretches they cover.
    """
    files = list(files)
    n = len(files)
    out = np.full(n, np.nan, dtype=float)
    if n == 0:
        return out

    # Short runs (and stride=1) are not worth bracketing.
    if stride <= 1 or n <= COARSE_MIN_FRAMES:
        _scan_indices(files, range(n), profile, workers, out, progress,
                      scanned=scanned)
        return out

    coarse_idx = list(range(0, n, stride))
    head = list(range(0, min(n, BASELINE_FRAMES * 2)))
    total = len(coarse_idx) + len(head) + COARSE_DENSE_GUESS
    done = _scan_indices(files, coarse_idx, profile, workers, out,
                         progress, 0, total, scanned=scanned)

    bracket = _motion_bracket(out[coarse_idx])
    if bracket is None:                       # nothing moved: coarse is enough
        _scan_indices(files, head, profile, workers, out, progress, done,
                      total, scanned=scanned)
        return out

    lo = max(0, (bracket[0] - COARSE_MARGIN) * stride)
    hi = min(n - 1, (bracket[1] + COARSE_MARGIN) * stride)
    dense = sorted(set(head) | set(range(lo, hi + 1)) - set(coarse_idx))
    _scan_indices(files, dense, profile, workers, out, progress, done,
                  max(total, done + len(dense)), scanned=scanned)
    return out


def _motion_bracket(coarse):
    """``(first, last)`` coarse indices spanning the stroke.

    Keyed off the STEP between coarse samples, not the displacement from the
    baseline. The piston does not spring back after the shot -- it stays where
    it stopped -- so a displacement test reads "moved" for every frame from
    the onset to the end of the recording and brackets half the burst. Motion
    is what actually delimits the stroke, and the separation is enormous at
    this stride: ~13 px per coarse step mid-stroke against ~0.05 px of drift.

    This only has to be generous; the dense pass and the onset walk back
    settle the exact frames.
    """
    series = _filled(coarse)
    if series is None or series.size < 4:
        return None
    steps = np.abs(np.diff(series, prepend=series[0]))
    moving = steps > max(MOVE_ABS_PX, COARSE_STEP_FRAC * float(steps.max()))
    if not moving.any():
        return None
    hits = np.flatnonzero(moving)
    return int(hits[0]) - 1, int(hits[-1])


def _filled(x):
    """Linear-interpolate isolated NaNs so the series can be differenced."""
    x = np.asarray(x, dtype=float)
    valid = np.isfinite(x)
    if not valid.any():
        return None
    idx = np.arange(x.size)
    return np.interp(idx, idx[valid], x[valid])


def _median_filter(series, window=MEDIAN_WINDOW):
    """Running median: removes single-frame position spikes without shifting
    the step at the stroke onset (a mean filter would smear it)."""
    window = int(window)
    if window <= 1 or series.size < window:
        return series
    pad = window // 2
    padded = np.pad(series, pad, mode="edge")
    strided = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.median(strided, axis=1)


def implausible_steps(x, max_step=MAX_STEP_PX):
    """Frames whose position moved further than the piston physically can.

    A True here means the detector switched between parts of the silhouette,
    not that the piston jumped -- see MAX_STEP_PX. Returned as a mask so the
    caller can report those frames instead of quoting a speed from them.
    """
    x = np.asarray(x, dtype=float)
    series = _filled(x)
    if series is None:
        return np.zeros(x.size, dtype=bool)
    steps = np.abs(np.diff(series, prepend=series[0]))
    return steps > max_step


def detect_piston_bounds(x, baseline_frames=BASELINE_FRAMES,
                         hold=HOLD_FRAMES, abs_px=MOVE_ABS_PX,
                         sigma_k=MOVE_SIGMA_K, confirm=MOVE_CONFIRM,
                         travel_frac=MOVE_TRAVEL_FRAC):
    """``(start, end)`` frame indices of the stroke, or ``None`` if it never moved.

    *start* is the first frame whose edge has left the pre-injection baseline
    by more than the noise floor and stays out for ``confirm`` frames; *end* is
    the first frame after that whose position holds still for ``hold`` frames
    (the piston has bottomed out), else the last frame.

    The floor is the largest of an absolute px minimum, the head frames' noise
    sigma, and ``travel_frac`` of the travel actually observed in the run -- see
    MOVE_TRAVEL_FRAC for why the sigma alone is not enough on real data.
    """
    series = _filled(x)
    if series is None or series.size < baseline_frames + confirm + 2:
        return None
    series = _median_filter(series)

    head = series[:baseline_frames]
    baseline = float(np.median(head))
    sigma = float(np.median(np.abs(head - baseline))) * 1.4826
    travel = float(np.max(series) - np.min(series))
    # Two thresholds. The trigger is deliberately coarse so baseline wander
    # cannot fire it; the noise floor is what actually separates movement from
    # rest. Using the trigger alone would place the onset several frames into
    # the stroke and under-report both the travel and the duration.
    noise_floor = max(abs_px, sigma_k * sigma)
    trigger = max(noise_floor, travel_frac * travel)

    displacement = np.abs(series - baseline)
    moved = displacement > trigger
    confirmed = None
    for i in range(baseline_frames, series.size - confirm + 1):
        if moved[i : i + confirm].all():
            confirmed = i
            break
    if confirmed is None:
        return None

    # Walk back from the confirmed stroke to where the piston first left rest,
    # by local step rather than displacement from the baseline -- see
    # ONSET_SPEED_FRAC for why the displacement test cannot do this job.
    steps = np.abs(np.diff(series, prepend=series[0]))
    stroke_step = float(
        np.median(steps[confirmed : confirmed + ONSET_STEP_SAMPLE]))
    quiet = max(ONSET_STEP_FLOOR, ONSET_SPEED_FRAC * stroke_step)
    start = confirmed
    limit = max(0, confirmed - MAX_ONSET_WALK)
    still = 0
    for i in range(confirmed, limit, -1):
        if steps[i] > quiet:
            start = i
            still = 0
            continue
        still += 1
        if still >= ONSET_QUIET:
            break

    # The plateau tolerance scales with the stroke's OWN motion, not with a
    # fixed displacement: how far the piston travels across `hold` frames
    # shrinks as the frame rate rises, so a fixed tolerance eventually exceeds
    # it and the stroke itself reads as a plateau. At 1048 fps the piston
    # covers ~25 px per hold window against a ~6 px trigger (fine); at 2511 fps
    # it covers 6.4 px against the same 6.4 px trigger, and run
    # 2026-08-13-09-31-20 ended 34 frames in, on a 128 px stroke.
    plateau_tol = max(MOVE_ABS_PX, PLATEAU_STEP_FRAC * stroke_step * hold)
    end = series.size - 1
    for i in range(confirmed + 1, series.size - hold + 1):
        window = series[i : i + hold]
        if float(window.max() - window.min()) <= plateau_tol:
            # The coarse window fits while the piston is still creeping the
            # last few px, so take the first frame that actually reached the
            # resting position -- otherwise the travel is under-reported.
            level = float(np.median(window))
            end = i
            for j in range(confirmed, series.size):
                if abs(series[j] - level) <= noise_floor:
                    end = j
                    break
            break
    return int(start), int(max(end, start))


def load_capture_meta(source_dir):
    """Return ``(fps, frame_times_us)`` recorded by Capture Piston, or
    ``(None, None)`` for a folder that came from anywhere else."""
    path = Path(source_dir) / CAPTURE_META_NAME
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    fps = meta.get("fps")
    try:
        fps = float(fps) if fps else None
    except (TypeError, ValueError):
        fps = None
    times = meta.get("frame_times_us")
    return fps, (list(times) if times else None)


def locate_stroke(x, hold=HOLD_FRAMES):
    """``(start, end)`` of the injection inside a whole BURST, or ``None``.

    Separate from :func:`detect_piston_bounds` because the two see different
    signals and only one of them can be solved this way. A burst is ~98% rest
    with the shot somewhere inside it; the copied window measure_piston works
    on is ~72% stroke. The rules below estimate "how still is still" from the
    series itself, which is sound for a burst and nonsense for a window that is
    mostly motion -- using one function for both silently halved a 27 U stroke
    (rig runs 2026-08-14-10-*, 9.25 mm read as 8.19 mm).

    What this does that a burst needs and a window does not:

    * The trigger measures displacement from a LOCAL baseline -- the mean of
      the preceding TRIGGER_WINDOW frames. Against the run's opening frames it
      cannot work at any threshold, because the stroke is proportional to the
      dose while the barrel drift it must clear is not: a 4 U shot moves 27 px
      after the barrel has wandered 0.9 px, and 5%-of-travel puts the trigger
      at 1.4 px, firing on the wander 50 frames early.
    * It anchors on the PEAK of that signal rather than the first crossing.
      The injection is the largest coherent movement in a burst, so the peak is
      inside it by construction; the first crossing is whatever wobbled first,
      and a touch of the rig 2600 frames early moved run 2026-08-07-15-55-38
      from (3516, 3736) to (867, 876).
    """
    series = _filled(x)
    if series is None or series.size < BASELINE_FRAMES + MOVE_CONFIRM + 2:
        return None
    series = _median_filter(series)

    window = int(min(TRIGGER_WINDOW, max(4, series.size // 8)))
    local = series - _trailing_mean(series, window)
    # The quiet level of that signal. A burst is overwhelmingly at rest, so a
    # low percentile is the resting level wherever the shot happens to fall.
    quiet_local = float(np.percentile(np.abs(local), 25)) * 1.4826
    trigger = max(MOVE_ABS_PX, MOVE_SIGMA_K * quiet_local)

    peak = int(np.argmax(np.abs(local)))
    if abs(float(local[peak])) < trigger:
        return None                       # nothing in this burst moved at all

    steps = np.abs(np.diff(series, prepend=series[0]))
    lo = max(0, peak - ONSET_STEP_SAMPLE // 2)
    stroke_step = float(np.median(steps[lo : peak + ONSET_STEP_SAMPLE // 2 + 1]))

    # Walk back to the onset by local step -- see ONSET_SPEED_FRAC.
    still_tol = max(ONSET_STEP_FLOOR, ONSET_SPEED_FRAC * stroke_step)
    start = peak
    limit = max(0, peak - MAX_ONSET_WALK)
    still = 0
    for i in range(peak, limit, -1):
        if steps[i] > still_tol:
            start, still = i, 0
            continue
        still += 1
        if still >= ONSET_QUIET:
            break

    # ... and forward to the first plateau, then on to the frame that actually
    # reached the parked level. The plateau window fits while the piston is
    # still creeping, and its own median is mid-tail; the level has to come
    # from after it, where a burst has thousands of frames of the piston
    # sitting still.
    plateau_tol = max(MOVE_ABS_PX, PLATEAU_STEP_FRAC * stroke_step * hold)
    settle_tol = max(MOVE_ABS_PX, MOVE_SIGMA_K * quiet_local)
    end = series.size - 1
    for i in range(peak + 1, series.size - hold + 1):
        block = series[i : i + hold]
        if float(block.max() - block.min()) <= plateau_tol:
            parked = series[i + hold : i + hold + SETTLE_SAMPLE]
            level = float(np.median(parked)) if parked.size else float(
                np.median(block))
            end = i
            for j in range(peak, series.size):
                if abs(series[j] - level) <= settle_tol:
                    end = j
                    break
            break
    return int(start), int(max(end, start))


def stroke_significance(xs, start, end):
    """``(travel_px, noise_px)`` for a detected stroke.

    *noise* is what the SAME measurement produces while the piston stands
    still, from the frames ahead of the onset, so the comparison scales with
    the run's own detection quality. A real injection clears it by more than an
    order of magnitude -- 60x for a 4 U shot -- while a burst that caught none
    sits at it.
    """
    series = _filled(xs)
    if series is None or end <= start:
        return 0.0, MIN_TRAVEL_PX
    block = series[start : end + 1]
    travel = float(np.max(block) - np.min(block))
    head = series[:start]
    sigma = 0.0
    if head.size >= BASELINE_FRAMES:
        sigma = float(np.median(np.abs(head - np.median(head)))) * 1.4826
    return travel, max(MIN_TRAVEL_PX, MIN_TRAVEL_SIGMA * sigma)


def _trailing_mean(series, window):
    """Mean of the *window* frames preceding each index (the first *window*
    frames keep their own value, so they read as no displacement)."""
    totals = np.concatenate([[0.0], np.cumsum(series)])
    out = np.array(series, dtype=float, copy=True)
    if series.size > window:
        out[window:] = (totals[window:-1] - totals[:-window - 1]) / window
    return out


def extract_piston_event(source_dir, dest_base, before=30, after=30,
                         fps=None, frame_times_us=None, progress=None,
                         copy=True, fast=False):
    """Detect the stroke in *source_dir* and copy the padded window out.

    Writes ``piston_meta.json`` into the destination: a SUPERSET of
    ``injection_meta.json`` (same ``pre_frames`` / ``onset_index`` /
    ``copy_start`` / ``copy_end`` keys) plus the timing needed to turn frame
    indices into seconds.

    With ``fast=True`` the stroke is located by :func:`scan_positions` instead
    of a full per-frame fit -- same window, a fraction of the time. The copied
    frames and everything measured from them are identical either way.
    """
    source_dir = Path(source_dir)
    files = injection_extract.list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")

    if fps is None and frame_times_us is None:
        fps, frame_times_us = load_capture_meta(source_dir)

    scanned = np.zeros(len(files), dtype=bool)
    if fast:
        profile = build_profile(files)
        positions = scan_positions(files, profile, progress=progress,
                                   scanned=scanned)
        tracked = {"x": positions, "profile": profile}
    else:
        tracked = track(files, progress=progress)
        scanned[:] = True
    # Diagnose a contrast failure BEFORE blaming the stroke. The piston is
    # found as a run of genuinely black pixels, so an over-exposed burst --
    # where the body washes out to mid-grey -- yields an edge in only some
    # frames, and the stroke that survives is a fragment of the real one. Rig
    # run 2026-08-13-09-02-14 at 320x64 detected 47% of frames (piston at 57
    # grey against a 66 threshold) and reported a "4 frame" stroke, which sent
    # the operator looking at the injector instead of the exposure.
    # Rate over the frames actually READ: the coarse-to-fine scan never looks
    # at most of them, and counting those as failures condemned a burst with
    # 100% detection as a 59% one.
    looked = max(1, int(np.count_nonzero(scanned)))
    found = int(np.count_nonzero(np.isfinite(tracked["x"])))
    if found < MIN_DETECT_FRAC * looked:
        profile = tracked["profile"]
        rule = ("the barrel does not darken enough at the piston's edge"
                if profile.short else "the body is not dark enough to separate "
                "from the barrel")
        raise RuntimeError(
            f"The piston edge was found in only {found} of {looked} frames "
            f"read ({100.0 * found / looked:.0f}%): {rule} (levels "
            f"{profile.dark:.0f} dark / {profile.bright:.0f} bright, needs "
            f"pixels below {profile.edge_thresh:.0f}). Lower the exposure and "
            "capture again -- the frame rate is set by the ROI height, not the "
            "exposure, so a shorter exposure costs nothing.")

    bounds = locate_stroke(tracked["x"])
    if bounds is None:
        raise RuntimeError(
            "No piston movement detected. The edge never leaves its resting "
            "position -- check that the injector fired during the capture.")

    start, end = bounds
    # A burst where the injector never fired, or that started after the shot,
    # still yields a "stroke" of a few frames; every number measured from it
    # would be meaningless. Both tests are dose-independent -- see
    # MIN_STROKE_MS -- so a small dose is measured, not rejected.
    travel, noise = stroke_significance(tracked["x"], start, end)
    duration_ms = (end - start + 1) / fps * 1000.0 if fps else None
    if travel < noise or (duration_ms is not None
                          and duration_ms < MIN_STROKE_MS):
        span = (f"{duration_ms:.1f} ms" if duration_ms is not None
                else f"{end - start + 1} frame(s)")
        raise RuntimeError(
            f"No measurable injection in this burst: the edge moved "
            f"{travel:.1f} px over {span}, against a resting noise level of "
            f"{noise:.1f} px. The injector probably did not fire, or the "
            "capture started after it did. Capture again, firing a second or "
            "so into the window.")
    copy_start = max(0, start - int(before))
    copy_end = min(len(files) - 1, end + int(after))
    selected = files[copy_start : copy_end + 1]

    fps, frame_times_us = _window_timing(fps, frame_times_us, copy_start, copy_end)
    meta = {
        "pre_frames": int(start - copy_start),
        "onset_index": int(start),
        "copy_start": int(copy_start),
        "copy_end": int(copy_end),
        "end_index": int(end),
        "method": "piston edge tracking",
        "fps": fps,
        "frame_times_us": frame_times_us,
        "band": tracked["profile"].as_dict(),
    }

    dest_dir = injection_extract.make_dest_dir(source_dir, dest_base)
    if copy:
        import shutil

        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            (dest_dir / META_NAME).write_text(
                json.dumps(meta, indent=2), encoding="utf-8")
            # measure_angle's pre-onset background reads this name; writing it
            # too keeps a piston folder usable by the spray tools.
            (dest_dir / "injection_meta.json").write_text(
                json.dumps({k: meta[k] for k in
                            ("pre_frames", "onset_index", "copy_start",
                             "copy_end", "method")}, indent=2),
                encoding="utf-8")
        except OSError:
            pass                          # metadata is an optimization
        for src in selected:
            shutil.copy2(src, dest_dir / src.name)

    return {
        "source_dir": str(source_dir),
        "dest_dir": str(dest_dir),
        "method": "piston edge tracking",
        "total_frames": len(files),
        "move_start_index": int(start),
        "move_end_index": int(end),
        "move_start_frame": files[start].name,
        "move_end_frame": files[end].name,
        "move_count": end - start + 1,
        "copy_start_frame": files[copy_start].name,
        "copy_end_frame": files[copy_end].name,
        "selected_count": len(selected),
        "before": int(before),
        "after": int(after),
        "stroke_px": float(tracked["x"][end] - tracked["x"][start]),
        "fps": fps,
        "copied": copy,
    }


def _window_timing(fps, frame_times_us, copy_start, copy_end):
    """Slice the burst's per-frame timestamps down to the copied window."""
    if not frame_times_us:
        return fps, None
    times = list(frame_times_us)[copy_start : copy_end + 1]
    if len(times) < 2:
        return fps, None
    base = times[0]
    return fps, [int(t - base) for t in times]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="a burst folder of piston frames")
    parser.add_argument("--dest", default=None, help="destination base folder")
    parser.add_argument("--before", type=int, default=30)
    parser.add_argument("--after", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true",
                        help="detect only, do not copy")
    parser.add_argument("--fast", action="store_true",
                        help="V2: parallel scan instead of a full per-frame fit")
    args = parser.parse_args()

    def progress(done, total):
        print(f"\rTracking {done}/{total}", end="", flush=True)

    result = extract_piston_event(
        args.source, dest_base=args.dest, before=args.before,
        after=args.after, progress=progress, copy=not args.dry_run,
        fast=args.fast)
    print()
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
