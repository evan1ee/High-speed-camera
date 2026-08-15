# tests/hardware/test_fake.py
"""FakeCamera replays a real burst, so tests above the seam run on rig pixels."""
from pathlib import Path

import numpy as np
import pytest

from hsc.hardware.device import CaptureConfig, CameraError
from hsc.hardware.fake import FakeCamera

BURST = Path(__file__).resolve().parents[1] / "fixtures" / "burst_320x120"
CFG = CaptureConfig(width=320, height=120, exposure_us=500.0)


def _started(**kwargs):
    cam = FakeCamera(BURST, **kwargs)
    cam.open(1)
    cam.configure(CFG)
    cam.start()
    return cam


def test_grab_returns_frames_in_order_with_real_pixels():
    cam = _started()
    first = cam.grab(1000)
    second = cam.grab(1000)
    assert first.shape == (120, 320)
    assert first.pixels.dtype == np.uint8
    assert first.pixels.max() > 200      # the bright barrel is really there
    assert not np.array_equal(first.pixels, second.pixels)


def test_block_ids_are_consecutive_and_timestamps_advance_at_the_given_fps():
    cam = _started(fps=1000.0)
    frames = [cam.grab(1000) for _ in range(3)]
    assert [f.block_id for f in frames] == [1, 2, 3]
    deltas = np.diff([f.timestamp for f in frames])
    assert set(deltas) == {1_000_000}    # 1 ms in nanosecond ticks


def test_dropped_frames_show_as_a_block_id_gap():
    """A dropped frame is invisible in the pixels; only blockId reveals it."""
    cam = _started(drop_after=2)
    ids = [cam.grab(1000).block_id for _ in range(4)]
    assert ids == [1, 2, 4, 5]


def test_grab_returns_none_when_the_burst_is_exhausted():
    cam = _started()
    for _ in range(12):
        assert cam.grab(1000) is not None
    assert cam.grab(1000) is None


def test_roi_override_lets_a_test_reproduce_the_wrong_size_burst():
    """Run 2026-08-13-09-18-35 delivered correctly-shaped frames at the wrong
    frame period. The guard that catches a size mismatch needs a camera that
    can lie about its size."""
    cam = _started(roi_override=(320, 240))
    frame = cam.grab(1000)
    assert (frame.width, frame.height) == (320, 240)


def test_configure_is_recorded_so_the_pre_burst_reprogram_can_be_asserted():
    cam = FakeCamera(BURST)
    cam.open(1)
    cam.configure(CFG)
    cam.start()
    cam.stop()
    cam.configure(CaptureConfig(320, 240, 500.0))
    cam.start()
    assert [(c.width, c.height) for c in cam.configs] == [(320, 120), (320, 240)]


def test_save_writes_a_byte_identical_copy_of_the_source_frame():
    cam = _started()
    frame = cam.grab(1000)
    out = BURST.parent / "tmp_saved.bmp"
    try:
        cam.save(frame, out)
        assert out.read_bytes() == sorted(BURST.glob("*.bmp"))[0].read_bytes()
        assert cam.saved == [out]
    finally:
        out.unlink(missing_ok=True)


def test_clone_survives_release_of_the_original():
    cam = _started()
    frame = cam.grab(1000)
    clone = cam.clone(frame)
    original = frame.pixels.copy()
    cam.release(frame)
    assert np.array_equal(clone.pixels, original)


def test_grab_before_start_is_an_error():
    cam = FakeCamera(BURST)
    cam.open(1)
    cam.configure(CFG)
    with pytest.raises(CameraError, match="not grabbing"):
        cam.grab(1000)


def test_open_rejects_a_folder_with_no_frames(tmp_path):
    with pytest.raises(CameraError, match="no frames"):
        FakeCamera(tmp_path).open(1)
