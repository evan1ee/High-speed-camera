"""EventWriter: writes BMPs + meta in the background, reports completion."""
import json
import queue

import numpy as np

from hsc.frame_writer import EventWriter
from hsc import measure_angle


def _frames(n=5, w=64, h=48):
    return [np.full((h, w), 40 + i, np.uint8) for i in range(n)]


def test_writes_frames_and_meta(tmp_path):
    done = queue.Queue()
    w = EventWriter(lambda d, ok, msg: done.put((d, ok, msg)))
    dest = tmp_path / "ev1"
    frames = _frames()
    names = [f"frame_{i + 1:06d}.bmp" for i in range(len(frames))]
    meta = {"pre_frames": 2, "onset_index": 2, "copy_start": 0,
            "copy_end": 4, "method": "monitor"}
    w.submit(str(dest), names, frames, meta)
    d, ok, msg = done.get(timeout=10)
    w.close()
    assert ok and d == str(dest)
    for nm, f in zip(names, frames):
        back = measure_angle.load_gray(dest / nm)     # fast-BMP-path readable
        assert np.array_equal(back, f)
    assert json.loads((dest / "injection_meta.json").read_text()) == meta


def test_error_reported_not_raised(tmp_path):
    done = queue.Queue()
    w = EventWriter(lambda d, ok, msg: done.put((d, ok, msg)))
    bad = tmp_path / "file.txt"
    bad.write_text("in the way")
    w.submit(str(bad / "sub"), ["frame_000001.bmp"], _frames(1), {})
    d, ok, msg = done.get(timeout=10)
    w.close()
    assert not ok and msg


def test_multiple_events_in_order(tmp_path):
    done = queue.Queue()
    w = EventWriter(lambda d, ok, msg: done.put(d))
    for k in range(3):
        w.submit(str(tmp_path / f"ev{k}"), ["frame_000001.bmp"], _frames(1), {})
    order = [done.get(timeout=10) for _ in range(3)]
    w.close()
    assert order == [str(tmp_path / f"ev{k}") for k in range(3)]
