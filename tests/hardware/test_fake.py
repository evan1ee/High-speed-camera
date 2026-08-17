# tests/hardware/test_fake.py
"""FakeCamera replays a real burst, so tests above the seam run on rig pixels."""
from pathlib import Path

import numpy as np
import pytest

from hsc.hardware.device import CaptureConfig, CameraError
from hsc.hardware.fake import NO_FRAME_STATUS, OK_STATUS, FakeCamera

BURST = Path(__file__).resolve().parents[1] / "fixtures" / "burst_320x120"
CFG = CaptureConfig(width=320, height=120, exposure_us=500.0)


def _started(**kwargs):
    cam = FakeCamera(BURST, **kwargs)
    cam.open(1)
    cam.configure(CFG)
    cam.start()
    return cam


def _frame(cam, timeout_ms=1000):
    """The frame behind a successful grab. ``grab`` hands back the SDK's raw
    answer now (see device.Grab) -- what a non-OK status means is decided in
    hsc/rig/worker.py, where it can be tested."""
    grab = cam.grab(timeout_ms)
    assert grab.ok
    return grab.build()


def test_grab_returns_frames_in_order_with_real_pixels():
    cam = _started()
    first = _frame(cam)
    second = _frame(cam)
    assert first.shape == (120, 320)
    assert first.pixels.dtype == np.uint8
    assert first.pixels.max() > 200      # the bright barrel is really there
    assert not np.array_equal(first.pixels, second.pixels)


def test_block_ids_are_consecutive_and_timestamps_advance_at_the_given_fps():
    cam = _started(fps=1000.0)
    frames = [_frame(cam) for _ in range(3)]
    assert [f.block_id for f in frames] == [1, 2, 3]
    deltas = np.diff([f.timestamp for f in frames])
    assert set(deltas) == {1_000_000}    # 1 ms in nanosecond ticks


def test_dropped_frames_show_as_a_block_id_gap():
    """A dropped frame is invisible in the pixels; only blockId reveals it."""
    cam = _started(drop_after=2)
    ids = [_frame(cam).block_id for _ in range(4)]
    assert ids == [1, 2, 4, 5]


def test_an_exhausted_burst_grabs_a_non_ok_status_not_a_frame():
    """The camera has stopped delivering. It reports that as a status, and the
    status is all it reports -- the rig layer decides what it means."""
    cam = _started()
    for _ in range(12):
        assert cam.grab(1000).ok
    spent = cam.grab(1000)
    assert not spent.ok
    assert spent.status == NO_FRAME_STATUS
    # Nothing to build: reading the frame struct behind a failed grab is what
    # takes the process down on the real SDK.
    assert spent.build is None


def test_a_fault_status_is_reported_as_itself():
    """A real SDK reports a timeout and a fault through the same integer, so
    the fake can be given either. Nothing above the seam reads the value -- it
    is carried onto the burst so the reason survives."""
    cam = _started(fail_status=-101)
    for _ in range(12):
        cam.grab(1000)
    failed = cam.grab(1000)
    assert (failed.ok, failed.status, failed.ok_status) == (False, -101,
                                                            OK_STATUS)


def test_roi_override_lets_a_test_reproduce_the_wrong_size_burst():
    """Run 2026-08-13-09-18-35 delivered correctly-shaped frames at the wrong
    frame period. The guard that catches a size mismatch needs a camera that
    can lie about its size."""
    cam = _started(roi_override=(320, 240))
    frame = _frame(cam)
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
    frame = _frame(cam)
    out = BURST.parent / "tmp_saved.bmp"
    try:
        cam.save(frame, out)
        assert out.read_bytes() == sorted(BURST.glob("*.bmp"))[0].read_bytes()
        assert cam.saved == [out]
    finally:
        out.unlink(missing_ok=True)


def test_clone_survives_release_of_the_original():
    cam = _started()
    frame = _frame(cam)
    clone = cam.clone(frame)
    original = frame.pixels.copy()
    cam.release(frame)
    assert np.array_equal(clone.pixels, original)


def test_configure_rejects_a_value_that_is_not_a_capture_config():
    cam = FakeCamera(BURST)
    cam.open(1)
    with pytest.raises(CameraError, match="CaptureConfig"):
        cam.configure({"width": 320, "height": 120})


def test_grab_before_start_is_an_error():
    cam = FakeCamera(BURST)
    cam.open(1)
    cam.configure(CFG)
    with pytest.raises(CameraError, match="not grabbing"):
        cam.grab(1000)


def test_saving_a_released_frame_is_an_error(tmp_path):
    """The real SDK's buffer is gone once released, so the fake refuses too --
    otherwise a save-after-release bug would only ever show up on the rig."""
    cam = _started()
    frame = _frame(cam)
    cam.release(frame)
    with pytest.raises(CameraError, match="released before saving"):
        cam.save(frame, tmp_path / "frame.bmp")


def test_open_rejects_a_folder_with_no_frames(tmp_path):
    with pytest.raises(CameraError, match="no frames"):
        FakeCamera(tmp_path).open(1)
