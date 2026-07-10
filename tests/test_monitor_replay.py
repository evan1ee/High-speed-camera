"""Replaying a recorded burst online must find the offline detector's event."""
import cv2
import numpy as np

from hsc import injection_extract, monitor


def _write_burst(folder, n=220, onset=40, end=90, w=160, h=120):
    folder.mkdir(parents=True)
    rng = np.random.default_rng(0)
    scene = np.full((h, w), 15, np.uint8)
    for i in range(n):
        f = scene.copy()
        if onset <= i < end:      # turbulent jet: pixels re-randomize per frame
            f[55:65, 20:60] = rng.integers(100, 221, size=(10, 40), dtype=np.uint8)
        cv2.imwrite(str(folder / f"frame_{i + 1:06d}.bmp"), f)


def test_replay_agrees_with_offline_detector(tmp_path):
    src = tmp_path / "burst"
    _write_burst(src)
    events = monitor.replay(src, before=5, after=30, min_peak=300)
    assert len(events) == 1
    ev = events[0]

    files = injection_extract.list_frames(src)
    signal, _ = injection_extract.compute_motion_signal_best(files)
    getter = injection_extract.raw_downsample_getter(files)
    off = injection_extract.detect_bounds_with_presence(
        np.asarray(signal), getter, len(files))
    assert off is not None
    off_start, off_end, _ = off

    # Tolerance gate: onset within the walk gap; the ends differ by up to the
    # offline smoothing lag -- but the SAVED window must fully cover the
    # offline injection core.
    kept_first = int(ev["names"][0][6:12]) - 1
    kept_last = int(ev["names"][-1][6:12]) - 1
    assert abs((kept_first + 5) - off_start) <= 5       # onset agreement
    assert kept_first <= max(0, off_start - 5)          # covers before-padding
    assert kept_last >= off_end                          # covers the full jet
    assert kept_last <= off_end + 30 + 60                # doesn't run away


def test_replay_drops_low_peak_events(tmp_path):
    """With the default MON_MIN_PEAK, the same ~400-px synthetic event is a
    drip-level disturbance and must be dropped from the replay results."""
    src = tmp_path / "burst"
    _write_burst(src)
    assert monitor.replay(src, before=5, after=30) == []
    kept = monitor.replay(src, before=5, after=30, keep_discarded=True)
    assert len(kept) == 1 and kept[0]["discarded"] != ""
