"""MonitorEngine: online trigger, presence-based end, ring buffer, padding."""
import numpy as np

from hsc import injection_extract
from hsc.monitor import MonitorEngine


W, H = 160, 120


def _scene():
    return np.full((H, W), 15, np.uint8)


def _jet():
    f = _scene()
    f[55:65, 20:60] = 220          # 400 px change on appearance > trigger 300
    return f


def _stream(events, n_total):
    """Frame stream: `events` is a list of (onset, end) index pairs."""
    for i in range(n_total):
        yield _jet() if any(a <= i < b for a, b in events) else _scene()


def test_single_event_window():
    eng = MonitorEngine(before=5, after=7)
    got = []
    # Jet on frames 40..69; presence smoothing (END_SMOOTH_WIN=21) + END_HOLD=25
    # means the end confirms around frame ~111 and the event closes ~118, so the
    # stream must run well past that.
    for i, f in enumerate(_stream([(40, 70)], 160)):
        ev = eng.feed(f)
        if ev is not None:
            got.append((i, ev))
    assert len(got) == 1
    closed_at, ev = got[0]
    start, end, peak = ev["bounds"]
    seq_onset_frame = ev["seq_names"][start]
    # The onset frame must be the global frame 40 (named by the global counter).
    assert seq_onset_frame == "frame_000041.bmp"     # 1-based naming
    # Window = onset-before .. end+after, and frames/names align.
    assert ev["window"][0] == max(0, start - 5)
    assert len(ev["frames"]) == len(ev["names"]) == ev["window"][1] - ev["window"][0] + 1
    # End must be at/after the jet vanished (frame 70) and the event must close
    # only after the `after` padding.
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
    eng = MonitorEngine(before=5, after=5)
    events = []
    # Event 1 (30..59) closes ~106; event 2 fires at 200 with plenty of armed
    # gap, ends 230, closes ~276. Stream to 320 to cover both closures.
    for f in _stream([(30, 60), (200, 230)], 320):
        ev = eng.feed(f)
        if ev:
            events.append(ev)
    assert len(events) == 2
    assert events[0]["seq_names"][events[0]["bounds"][0]] == "frame_000031.bmp"
    assert events[1]["seq_names"][events[1]["bounds"][0]] == "frame_000201.bmp"


def test_runaway_cap_closes_a_never_ending_jet():
    eng = MonitorEngine(before=5, after=5, max_event_frames=50)
    ev = None
    for f in _stream([(10, 10_000)], 200):
        ev = eng.feed(f) or ev
    assert ev is not None
    assert ev["dropped_note"] != ""          # cap fired, honestly recorded


def test_flush_returns_partial_event():
    eng = MonitorEngine(before=5, after=5)
    for f in _stream([(20, 10_000)], 40):    # stop mid-jet
        eng.feed(f)
    ev = eng.flush()
    assert ev is not None and len(ev["frames"]) > 0
    assert eng.flush() is None               # idempotent


def test_feed_meets_perf_budget():
    import time
    eng = MonitorEngine(before=30, after=30)
    frames = [f for f in _stream([(100, 160)], 400)]
    big = [np.kron(f, np.ones((2, 2), np.uint8)) for f in frames]  # 320x240
    t0 = time.perf_counter()
    for f in big:
        eng.feed(f)
    per_frame = (time.perf_counter() - t0) / len(big)
    assert per_frame < 0.0015, f"feed averaged {per_frame * 1e3:.2f} ms/frame"
