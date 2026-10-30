"""Piston edge tracking on synthetic frames with exact ground truth.

The rig's piston is a DARK body on a BRIGHT barrel interior (the inverse of
the water jet), so these tests pin the new detector's three jobs: find the
barrel band between the dark walls, locate the piston's left edge to
sub-pixel accuracy despite clutter, and turn the position series into
injection start/end frames.
"""

import numpy as np
import pytest

from hsc import piston_track as pt


WIDTH, HEIGHT = 320, 240
WALL_LO, WALL_HI = 60, 180          # bright barrel interior rows (inclusive)
BRIGHT, DARK = 220.0, 35.0
BODY_W = 90                         # px of dark piston body behind its left edge


def make_frame(edge_x=40.0, tilt=0.0, noise=0.0, seed=0, streak=None,
               body_w=BODY_W, width=WIDTH, height=HEIGHT,
               seal=None, sliver=None, body_rows=None):
    """Synthetic piston frame.

    Bright barrel interior between two dark walls, holding a dark piston body
    ``body_w`` px wide with bright fluid chamber ahead of it (as on the rig --
    not a dark half-plane). Both of the body's edges are anti-aliased so the
    left one has a true sub-pixel position: intensity falls as
    ``dark + A * clip(x_e - col + 0.5, 0, 1)``, whose steepest descent sits
    exactly on ``x_e``.

    *tilt* slants the edge (px of x per row from the band centre). *streak* is
    ``(x0, length)`` of a short dark artefact inside the band left of the piston
    -- mist/residue that must NOT be mistaken for the piston body.

    The remaining arguments reproduce what the rig actually shows (2026-08-07):
    *seal* ``(x0, width)`` is the narrow dark bar at the barrel end that stays
    put while the piston travels away from it; *sliver* ``(offset, width)`` is
    the bright reflection just behind the piston's leading rim, which splits
    the body in some rows and not others; *body_rows* ``(lo, hi)`` makes the
    piston shorter than the barrel, leaving barrel rows that hold no piston.
    """
    cols = np.arange(width, dtype=np.float64)
    centre = 0.5 * (WALL_LO + WALL_HI)
    img = np.full((height, width), DARK, dtype=np.float64)

    for row in range(WALL_LO, WALL_HI + 1):
        if body_rows is not None and not (body_rows[0] <= row <= body_rows[1]):
            img[row] = BRIGHT              # barrel interior, no piston here
            continue
        x_e = edge_x + tilt * (row - centre)
        left = np.clip(x_e - cols + 0.5, 0.0, 1.0)        # 1 left of the body
        right = np.clip(cols - (x_e + body_w) + 0.5, 0.0, 1.0)  # 1 right of it
        img[row] = DARK + (BRIGHT - DARK) * np.clip(left + right, 0.0, 1.0)
        if sliver is not None and row % 2 == 0:
            offset, gap_w = sliver
            start = int(round(x_e + offset))
            img[row, start : start + gap_w] = BRIGHT

    if seal is not None:
        x0, seal_w = seal
        img[WALL_LO:WALL_HI + 1, x0 : x0 + seal_w] = DARK

    if streak is not None:
        x0, length = streak
        img[WALL_LO + 5 : WALL_HI - 5, x0 : x0 + length] = DARK

    # Clutter outside the band: the holder at bottom-left, the rod at top.
    img[HEIGHT - 30 :, :60] = DARK
    img[:20, 200:240] = DARK

    if noise > 0:
        rng = np.random.default_rng(seed)
        img = img + rng.normal(0.0, noise, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def make_run(positions, noise=1.5, tilt=0.0):
    return [make_frame(edge_x=x, tilt=tilt, noise=noise, seed=i)
            for i, x in enumerate(positions)]


# ---------------------------------------------------------------- band ----
def test_find_barrel_band_lands_inside_the_interior():
    frames = make_run([40.0, 60.0, 120.0, 200.0], noise=0.0)
    profile = pt.build_profile(frames)
    assert WALL_LO <= profile.row_lo < profile.row_hi <= WALL_HI
    assert profile.row_hi - profile.row_lo >= pt.MIN_BAND_ROWS


def test_profile_levels_bracket_the_threshold():
    profile = pt.build_profile(make_run([40.0, 150.0], noise=0.0))
    assert profile.dark < profile.thresh < profile.bright


# ---------------------------------------------------------------- edge ----
@pytest.mark.parametrize("edge_x", [40.0, 40.3, 87.6, 199.5])
def test_edge_is_subpixel_accurate(edge_x):
    profile = pt.build_profile(make_run([30.0, edge_x, 250.0], noise=0.0))
    fit = pt.measure_frame_edge(make_frame(edge_x=edge_x, noise=1.0), profile)
    assert fit is not None
    assert fit["x"] == pytest.approx(edge_x, abs=0.3)


def test_edge_tilt_is_recovered():
    profile = pt.build_profile(make_run([30.0, 100.0, 250.0], noise=0.0))
    fit = pt.measure_frame_edge(
        make_frame(edge_x=100.0, tilt=0.05, noise=1.0), profile)
    assert fit is not None
    assert fit["k"] == pytest.approx(0.05, abs=0.01)
    assert fit["n_points"] >= pt.MIN_EDGE_POINTS


def test_short_dark_streak_is_not_mistaken_for_the_piston():
    """A 4 px mist streak at x=15 is shorter than MIN_DARK_RUN and must be
    walked past -- otherwise every measured distance is wrong by ~25 px."""
    profile = pt.build_profile(make_run([30.0, 100.0, 250.0], noise=0.0))
    gray = make_frame(edge_x=100.0, noise=1.0, streak=(15, 4))
    fit = pt.measure_frame_edge(gray, profile)
    assert fit is not None
    assert fit["x"] == pytest.approx(100.0, abs=0.3)


def test_edge_off_frame_returns_none():
    profile = pt.build_profile(make_run([30.0, 100.0], noise=0.0))
    blank = np.full((HEIGHT, WIDTH), int(BRIGHT), dtype=np.uint8)
    assert pt.measure_frame_edge(blank, profile) is None


# --------------------------------------------------------------- track ----
def _stroke(pre=30, move=100, post=40, x0=40.0, step=1.2):
    """Static, then a constant-speed stroke, then static again."""
    positions = [x0] * pre
    positions += [x0 + step * (i + 1) for i in range(move)]
    return positions + [positions[-1]] * post


def test_track_follows_the_stroke():
    positions = _stroke()
    result = pt.track(make_run(positions))
    assert result["x"].shape == (len(positions),)
    assert np.nanmax(np.abs(result["x"] - np.array(positions))) < 0.4


def test_detect_bounds_finds_the_moving_span():
    pre, move = 30, 100
    result = pt.track(make_run(_stroke(pre=pre, move=move)))
    bounds = pt.detect_piston_bounds(result["x"])
    assert bounds is not None
    start, end = bounds
    assert abs(start - pre) <= 3
    assert abs(end - (pre + move)) <= 5


def test_v2_scan_finds_the_same_stroke_as_the_full_fit():
    """Find piston V2 drops the per-frame RANSAC/TLS fit and reads in
    parallel. It may only do that if it lands on the same window -- the whole
    point is that the operator's result does not depend on the checkbox."""
    frames = make_run(_stroke())
    profile = pt.build_profile(frames)
    fast = pt.scan_positions(frames, profile)
    slow = pt.track(frames, profile=profile)["x"]

    assert np.isfinite(fast).sum() == np.isfinite(slow).sum()
    fast_bounds = pt.detect_piston_bounds(fast)
    slow_bounds = pt.detect_piston_bounds(slow)
    assert fast_bounds is not None and slow_bounds is not None
    # Padding is 30 frames either side, so a frame or two of slack is harmless.
    assert abs(fast_bounds[0] - slow_bounds[0]) <= 2
    assert abs(fast_bounds[1] - slow_bounds[1]) <= 2


def test_v2_scan_preserves_frame_order():
    """The parallel pool must not reorder results: frame i's position has to
    stay at index i, or the stroke lands at the wrong time."""
    positions = _stroke(pre=5, move=40, post=5)
    frames = make_run(positions, noise=0.0)
    profile = pt.build_profile(frames)
    scanned = pt.scan_positions(frames, profile, workers=4)
    assert np.nanmax(np.abs(np.diff(scanned) - np.diff(positions))) < 0.5


def test_onset_ignores_slow_baseline_drift():
    """Over a long burst the barrel drifts further than any displacement
    floor. The onset must be found from the LOCAL step, or the walk back runs
    into the drift and copies hundreds of resting frames into the window --
    rig run 2026-08-12-14-07-22 lost 194 frames (185 ms) exactly that way.
    """
    rng = np.random.default_rng(0)
    n_rest, n_move = 300, 90
    # 2 px of drift across the head: far above MOVE_ABS_PX, far below a step.
    rest = 40.0 + np.linspace(0.0, 2.0, n_rest) + rng.normal(0, 0.05, n_rest)
    stroke = rest[-1] + np.cumsum(np.full(n_move, 1.7))
    x = np.concatenate([rest, stroke, np.full(40, stroke[-1])])

    bounds = pt.detect_piston_bounds(x)
    assert bounds is not None
    start, end = bounds
    assert abs(start - n_rest) <= 3, f"onset {start} walked back into the drift"
    assert abs(end - (n_rest + n_move)) <= 5


def test_coarse_to_fine_scan_matches_a_full_scan():
    """The fast scan reads only the frames around the stroke, so it must find
    the same window a full scan does -- including when the piston STAYS
    displaced afterwards, which is what defeats a displacement-based bracket.
    """
    pre, move, post = 250, 60, 150
    x0 = 40.0
    positions = [x0] * pre
    positions += [x0 + 2.0 * (i + 1) for i in range(move)]
    positions += [positions[-1]] * post
    frames = [make_frame(edge_x=x, noise=1.0, seed=i)
              for i, x in enumerate(positions)]
    profile = pt.build_profile(frames)

    full = pt.scan_positions(frames, profile, stride=1)
    fast = pt.scan_positions(frames, profile)

    looked = int(np.isfinite(fast).sum())
    assert looked < 0.6 * len(frames), f"read {looked} of {len(frames)} frames"

    b_full = pt.detect_piston_bounds(full)
    b_fast = pt.detect_piston_bounds(fast)
    assert b_full is not None and b_fast is not None
    assert abs(b_fast[0] - b_full[0]) <= 5
    assert abs(b_fast[1] - b_full[1]) <= 5


def test_locate_stroke_finds_a_small_dose_over_a_drifting_baseline():
    """A small dose is not a degenerate run. The stroke is proportional to the
    dose, so anything the trigger compares against a distant baseline scales
    with the dose while the barrel drift it must clear does not: on rig run
    2026-08-14-10-27-10 a 4 U shot moved 27 px after the barrel had wandered
    0.9 px, and a 5%-of-travel trigger fired on the wander 50 frames early."""
    rng = np.random.default_rng(5)
    n_rest, n_move = 3000, 30
    rest = 249.0 + np.linspace(0.0, 0.9, n_rest) + rng.normal(0, 0.01, n_rest)
    stroke = rest[-1] + np.cumsum(np.full(n_move, 27.0 / n_move))
    x = np.concatenate([rest, stroke, np.full(400, stroke[-1])])

    bounds = pt.locate_stroke(x)
    assert bounds is not None, "a 4 U stroke must not read as no injection"
    start, end = bounds
    assert abs(start - n_rest) <= 5, f"onset {start} fired on the drift"
    travel, noise = pt.stroke_significance(x, start, end)
    assert travel > noise
    assert travel == pytest.approx(27.0, rel=0.15)


def test_locate_stroke_ignores_an_early_wobble():
    """It anchors on the PEAK, not the first threshold crossing: a touch of the
    rig 2600 frames early moved run 2026-08-07-15-55-38 to (867, 876)."""
    rng = np.random.default_rng(6)
    x = np.concatenate([
        60.0 + rng.normal(0, 0.02, 900),
        62.0 + rng.normal(0, 0.02, 20),        # a brief 2 px wobble
        60.0 + rng.normal(0, 0.02, 900),
        60.0 + np.cumsum(np.full(150, 1.5)),   # the injection, 225 px
        np.full(500, 60.0 + 225.0)])
    start, end = pt.locate_stroke(x)
    assert start > 1500, f"onset {start} latched onto the early wobble"
    assert abs(start - 1820) <= 20


def test_measure_path_is_not_the_burst_path():
    """locate_stroke estimates 'how still is still' from the series itself,
    which is sound for a burst (~98% rest) and nonsense for the copied window
    measure_piston works on (~72% stroke). Sharing one function between them
    silently halved a 27 U stroke: 9.25 mm read as 8.19 mm on rig runs
    2026-08-14-10-*. The measure path must keep its own detector."""
    import inspect

    from hsc import measure_piston

    assert "locate_stroke" in inspect.getsource(pt.extract_piston_event)
    assert "locate_stroke" not in inspect.getsource(measure_piston)
    assert "detect_piston_bounds" in inspect.getsource(measure_piston)

    # A window that is mostly stroke: what measure_piston actually sees.
    window = np.concatenate([np.full(30, 100.0),
                             100.0 + np.cumsum(np.full(155, 1.0)),
                             np.full(30, 255.0)])
    bounds = pt.detect_piston_bounds(window)
    assert bounds is not None, "the measure detector must handle its own input"
    start, end = bounds
    assert start <= 35, f"onset {start} must stay in the leading padding"
    assert end >= 180, f"end {end} truncates the stroke"


def test_no_motion_detects_no_injection():
    result = pt.track(make_run([40.0] * 60))
    assert pt.detect_piston_bounds(result["x"]) is None


# ------------------------------------------- rig regressions (2026-08-07) ---
def test_seal_artefact_left_of_the_piston_is_ignored():
    """Once the stroke starts, a narrow dark seal stays behind at the barrel
    end. Taking the FIRST dark run locked onto it and reported 4 px of wobble
    instead of the real 268 px stroke."""
    profile = pt.build_profile(make_run([40.0, 120.0, 250.0], noise=0.0))
    gray = make_frame(edge_x=120.0, noise=1.0, seal=(23, 8))
    fit = pt.measure_frame_edge(gray, profile)
    assert fit is not None
    assert fit["x"] == pytest.approx(120.0, abs=0.5)


def test_seal_is_ignored_for_the_whole_stroke():
    """The same, tracked end to end: the seal must never capture the series."""
    positions = [40.0] * 20 + [40.0 + 2.0 * i for i in range(60)]
    frames = [make_frame(edge_x=x, noise=1.0, seed=i, seal=(23, 8))
              for i, x in enumerate(positions)]
    result = pt.track(frames)
    assert np.nanmax(np.abs(result["x"] - np.array(positions))) < 1.0


def test_bright_sliver_does_not_split_the_edge():
    """A reflection just behind the rim splits the body in half the rows. Left
    unclosed, the rows form two rival clusters and the fit flips between them
    from frame to frame -- which looked like +/-14 px of baseline noise."""
    profile = pt.build_profile(
        [make_frame(edge_x=x, sliver=(6, 3)) for x in (40.0, 120.0, 250.0)])
    fits = [pt.measure_frame_edge(
        make_frame(edge_x=40.0, noise=1.0, seed=i, sliver=(6, 3)), profile)
        for i in range(6)]
    assert all(fit is not None for fit in fits)
    xs = np.array([fit["x"] for fit in fits])
    assert xs.mean() == pytest.approx(40.0, abs=0.5)   # the OUTER edge
    assert np.ptp(xs) < 0.3                            # and it never flips


def test_band_excludes_barrel_rows_without_a_piston():
    """The barrel is taller than the piston; rows it never occupies supply
    edges from the holder and splash that can out-vote the real ones."""
    frames = [make_frame(edge_x=x, body_rows=(80, 150))
              for x in (40.0, 120.0, 200.0)]
    profile = pt.build_profile(frames)
    assert 80 <= profile.row_lo and profile.row_hi <= 150


def test_baseline_wander_does_not_trigger_the_stroke():
    """The resting position wanders a couple of px over thousands of frames.
    A threshold set from 20 head frames fired 2700 frames before the real
    stroke; the floor is now anchored to the travel actually present."""
    rng = np.random.default_rng(0)
    rest = 14.0 + rng.normal(0.0, 0.6, 3500)
    rest[900:930] += 2.0                       # a wander excursion, not a stroke
    stroke = 14.0 + np.linspace(0.0, 250.0, 200)
    series = np.concatenate([rest, stroke, np.full(300, 264.0)])

    bounds = pt.detect_piston_bounds(series)
    assert bounds is not None
    start, end = bounds
    assert start >= 3400, f"triggered on baseline wander at frame {start}"
    assert abs(start - 3500) <= 25
    assert abs(end - 3700) <= 25


def test_onset_is_not_delayed_by_the_coarse_trigger():
    """The trigger is set high to survive wander, so the onset is found by
    walking back to the noise floor -- otherwise the first frames of travel
    are cut off and both stroke and duration come out short."""
    series = np.concatenate([np.full(60, 20.0),
                             20.0 + np.linspace(0.0, 200.0, 150),
                             np.full(60, 220.0)])
    start, end = pt.detect_piston_bounds(series)
    assert abs(start - 60) <= 2
    assert abs(end - 209) <= 3


def test_seal_never_captures_the_tracked_edge():
    """The seal sits a few px behind the piston's rest position, so the piston
    advances right past it. Rules based on the leftmost dark pixel handed the
    edge to it at that moment and never got it back -- the whole stroke then
    read as zero travel."""
    positions = [40.0] * 10 + [40.0 + 3.0 * i for i in range(50)]
    frames = [make_frame(edge_x=x, noise=1.0, seed=i, seal=(24, 9))
              for i, x in enumerate(positions)]
    result = pt.track(frames)
    assert np.nanmax(np.abs(result["x"] - np.array(positions))) < 1.5
    # ... and specifically it did not get stuck once it passed the seal.
    assert result["x"][-1] == pytest.approx(positions[-1], abs=1.0)


def test_body_is_identified_by_blackness_not_position():
    """A mid-grey feature wider than MIN_BODY_RUN in front of the piston must
    not be taken for it: on the rig the collar and seal are 34-62 grey while
    the body is 3-15, and that is the only thing that separates them."""
    profile = pt.build_profile(make_run([40.0, 120.0, 250.0], noise=0.0))
    gray = make_frame(edge_x=140.0, noise=1.0)
    # A wide but only mid-grey band ahead of the body (a lit collar).
    grey_level = int((profile.dark + profile.bright) / 2) - 20
    gray[WALL_LO + 5 : WALL_HI - 5, 60:120] = grey_level
    fit = pt.measure_frame_edge(gray, profile)
    assert fit is not None
    assert fit["x"] == pytest.approx(140.0, abs=0.6)


def test_implausible_steps_flag_feature_switches():
    """A 25 px step between frames is ~1500 mm/s -- not the piston moving but
    the detector changing which part of the silhouette it calls the edge."""
    series = np.concatenate([np.arange(30) * 1.5,
                             np.arange(30) * 1.5 + 25.0])   # a 25 px switch
    flags = pt.implausible_steps(series)
    assert flags[30]
    assert flags.sum() == 1
    assert not pt.implausible_steps(np.arange(60) * 1.5).any()


def test_refine_band_keeps_only_the_flat_face():
    """Mid-stroke the silhouette is a staircase; the band must collapse onto
    the rows that share one rigid edge."""
    def stepped(edge_x, seed):
        gray = make_frame(edge_x=edge_x, noise=1.0, seed=seed)
        # A trailing skirt over the lower rows only, wide and black enough to
        # pass for the body on its own -- so only row agreement can reject it.
        gray[150:WALL_HI + 1, int(edge_x) - 50 : int(edge_x)] = int(DARK)
        return gray

    frames = [stepped(x, i) for i, x in enumerate(np.linspace(60, 200, 20))]
    profile = pt.build_profile(frames)
    refined = pt.refine_band(frames, profile)
    assert refined.row_hi < 150, "the skirt rows were not excluded"
    assert refined.n_rows >= pt.MIN_BAND_ROWS


def test_vectorised_parabolic_offsets_match_measure_angle():
    """piston_track refines a whole band of rows at once; the math must stay
    identical to the scalar helper the spray pipeline uses."""
    from hsc import measure_angle as ma

    rng = np.random.default_rng(3)
    grad = rng.normal(0.0, 5.0, (12, 40))
    cols = rng.integers(1, 39, size=12)
    got = pt._parabolic_offsets(grad, cols)
    want = [ma._parabolic_vertex_offset(grad[r], int(cols[r])) for r in range(12)]
    assert got == pytest.approx(want, abs=1e-12)


def test_distance_between_frames_matches_ground_truth():
    """Perpendicular distance from the start frame's line, the quantity the
    CSV reports -- must be the true displacement even with a tilted edge."""
    profile = pt.build_profile(make_run([40.0, 120.0, 250.0], noise=0.0))
    ref = pt.measure_frame_edge(make_frame(edge_x=40.0, tilt=0.04), profile)
    now = pt.measure_frame_edge(make_frame(edge_x=95.0, tilt=0.04), profile)
    assert pt.line_distance(ref, now, profile) == pytest.approx(55.0, abs=0.3)
