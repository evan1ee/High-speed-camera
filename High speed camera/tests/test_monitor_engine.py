"""MonitorEngine: online trigger, motion-quiet end, ring buffer, validation.

The synthetic jet is TURBULENT (its pixels re-randomize every frame): a real
water jet at high FPS changes hundreds of pixels per frame while it flows.
The 2026-07-10 on-rig session showed a static-looking synthetic jet tests the
wrong thing -- the end rule is about motion going quiet, and the wet scene
after a real injection is exactly "changed vs before, but static".
"""
import numpy as np

from hsc import injection_extract
from hsc.monitor import MON_DETECT_FRAC, MON_END_HOLD, MonitorEngine


W, H = 160, 120


def _scene():
    return np.full((H, W), 15, np.uint8)


def _jet_frame(rng):
    """One frame of a flowing jet: ~400 px re-randomized (turbulence)."""
    f = _scene()
    f[55:65, 20:60] = rng.integers(100, 221, size=(10, 40), dtype=np.uint8)
    return f


def _stream(events, n_total, wet_after=None):
    """Frame stream: `events` is a list of (onset, end) index pairs.

    With *wet_after*, every frame from that index on carries a STATIC bright
    patch (the scene changed permanently -- mist/wetness -- but nothing moves).
    """
    rng = np.random.default_rng(0)
    for i in range(n_total):
        f = _jet_frame(rng) if any(a <= i < b for a, b in events) else _scene()
        if wet_after is not None and i >= wet_after:
            f[80:100, 30:90] = 180
        yield f


def test_single_event_window():
    eng = MonitorEngine(before=5, after=7, min_peak=300)
    got = []
    # Jet on frames 40..69; the quiet run starts at ~70 and the event closes
    # MON_END_HOLD (60) frames later, ~130.
    for i, f in enumerate(_stream([(40, 70)], 160)):
        ev = eng.feed(f)
        if ev is not None:
            got.append((i, ev))
    assert len(got) == 1
    closed_at, ev = got[0]
    assert ev["discarded"] == ""
    start, end, peak = ev["bounds"]
    seq_onset_frame = ev["seq_names"][start]
    # The onset frame must be the global frame 40 (named by the global counter).
    assert seq_onset_frame == "frame_000041.bmp"     # 1-based naming
    # Window = onset-before .. end+after, and frames/names align.
    assert ev["window"][0] == max(0, start - 5)
    assert len(ev["frames"]) == len(ev["names"]) == ev["window"][1] - ev["window"][0] + 1
    # End must be at/after the jet stopped flowing (frame 70) and the event
    # must close only after the `after` padding.
    assert ev["seq_names"][end] >= "frame_000070.bmp"
    assert closed_at >= 70 + 7 - 1


def test_no_event_on_static_scene_and_memory_bounded():
    eng = MonitorEngine(before=5, after=7)
    for f in _stream([], 500):
        assert eng.feed(f) is None
    assert eng.stats["events"] == 0
    assert eng.stats["state"] == "armed"
    # Ring buffers are bounded regardless of how long we monitor.
    assert len(eng._ring) <= 5 + eng.walkback


def test_two_events_both_detected():
    eng = MonitorEngine(before=5, after=5, min_peak=300)
    events = []
    # Event 1 (30..59) closes ~120; event 2 fires at 200, ends 230, closes ~290.
    for f in _stream([(30, 60), (200, 230)], 320):
        ev = eng.feed(f)
        if ev:
            events.append(ev)
    assert len(events) == 2
    assert events[0]["seq_names"][events[0]["bounds"][0]] == "frame_000031.bmp"
    assert events[1]["seq_names"][events[1]["bounds"][0]] == "frame_000201.bmp"


def test_wet_scene_still_ends():
    """Regression (2026-07-10 rig session): the injection wets the scene, so
    every post-jet frame differs from the pre-trigger background forever. The
    motion-quiet end rule must still close the event promptly; v1's
    presence-vs-background rule never fired and ran into the runaway cap."""
    eng = MonitorEngine(before=5, after=7, min_peak=300)
    got = []
    for i, f in enumerate(_stream([(40, 70)], 200, wet_after=55)):
        ev = eng.feed(f)
        if ev is not None:
            got.append((i, ev))
    assert len(got) == 1
    closed_at, ev = got[0]
    assert ev["dropped_note"] == ""          # closed by the end rule, not the cap
    assert closed_at <= 70 + MON_END_HOLD + 7 + 5


def test_low_peak_event_discarded():
    """A drip/mist trigger (peak ~400 px << MON_MIN_PEAK 3000) must be
    returned as discarded so the GUI never saves or measures it."""
    eng = MonitorEngine(before=5, after=7)      # default min_peak
    got = [ev for f in _stream([(40, 70)], 160) if (ev := eng.feed(f))]
    assert len(got) == 1
    assert got[0]["discarded"] != ""
    assert eng.stats["events"] == 0
    assert eng.stats["discarded"] == 1


def test_runaway_cap_closes_a_never_ending_jet():
    eng = MonitorEngine(before=5, after=5, max_event_frames=50, min_peak=300)
    ev = None
    for f in _stream([(10, 10_000)], 200):
        ev = eng.feed(f) or ev
    assert ev is not None
    assert ev["dropped_note"] != ""          # cap fired, honestly recorded


def test_flush_returns_partial_event():
    eng = MonitorEngine(before=5, after=5, min_peak=300)
    for f in _stream([(20, 10_000)], 40):    # stop mid-jet
        eng.feed(f)
    ev = eng.flush()
    assert ev is not None and len(ev["frames"]) > 0
    assert eng.flush() is None               # idempotent


def test_right_third_disturbance_ignored():
    """Removing/reinstalling the nozzle (right side of the frame) churns
    pixels there but must not trigger: detection only watches the left
    MON_DETECT_FRAC (2/3) of the columns. The jet itself lives in the left
    2/3 and still triggers (covered by every other test)."""
    assert 0.6 < MON_DETECT_FRAC < 0.7
    eng = MonitorEngine(before=5, after=7, min_peak=300)
    rng = np.random.default_rng(1)
    x0 = int(W * MON_DETECT_FRAC) + 1           # strictly right of the cut
    for i in range(200):
        f = _scene()
        if 40 <= i < 120:                        # long, violent disturbance
            f[:, x0:] = rng.integers(0, 256, size=(H, W - x0), dtype=np.uint8)
        assert eng.feed(f) is None
    assert eng.flush() is None
    assert eng.stats["events"] == 0
    assert eng.stats["discarded"] == 0


def test_detect_frac_full_frame_still_triggers_on_right():
    """detect_frac=1.0 restores whole-frame detection (sanity of the crop)."""
    eng = MonitorEngine(before=5, after=7, min_peak=300, detect_frac=1.0)
    rng = np.random.default_rng(1)
    x0 = int(W * MON_DETECT_FRAC) + 1
    got = []
    for i in range(200):
        f = _scene()
        if 40 <= i < 70:
            f[55:65, x0:x0 + 40] = rng.integers(
                100, 221, size=(10, min(40, W - x0)), dtype=np.uint8)
        ev = eng.feed(f)
        if ev:
            got.append(ev)
    assert len(got) == 1 and got[0]["discarded"] == ""


def test_feed_meets_perf_budget():
    import time
    eng = MonitorEngine(before=30, after=30, min_peak=300)
    frames = [f for f in _stream([(100, 160)], 400)]
    big = [np.kron(f, np.ones((2, 2), np.uint8)) for f in frames]  # 320x240
    t0 = time.perf_counter()
    for f in big:
        eng.feed(f)
    per_frame = (time.perf_counter() - t0) / len(big)
    assert per_frame < 0.0015, f"feed averaged {per_frame * 1e3:.2f} ms/frame"
