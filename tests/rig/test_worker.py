#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The piston burst, finally testable.

Each test here pins a behaviour that was learned from a failed rig run and
previously had no coverage at all -- the frame-rate bug of 2026-08-13 was
invisible because nothing could execute this path.
"""
import json
from pathlib import Path

import pytest

from hsc.hardware.device import CameraError, CaptureConfig
from hsc.hardware.fake import FakeCamera
from hsc.rig.events import EventBus
from hsc.rig.worker import CameraWorker, WrongFrameSize

BURST = Path(__file__).resolve().parents[1] / "fixtures" / "burst_320x120"
CFG = CaptureConfig(width=320, height=120, exposure_us=500.0)


def _worker(tmp_path, bus=None, **kwargs):
    cam = FakeCamera(BURST, **kwargs)
    return CameraWorker(cam, bus or EventBus(), tmp_path / "captures"), cam


def _payloads(q):
    """Drain a subscriber into {kind: payload}."""
    seen = {}
    while not q.empty():
        event = q.get_nowait()
        seen[event.kind] = event.payload
    return seen


def test_burst_saves_every_frame_it_grabbed(tmp_path):
    worker, cam = _worker(tmp_path)
    result = worker.capture_piston(CFG, duration_s=10.0)
    saved = sorted(result.output_dir.glob("frame_*.bmp"))
    assert len(saved) == result.frames == 12
    assert cam.saved == saved


def test_camera_is_reprogrammed_before_the_burst(tmp_path):
    """configure_camera otherwise runs only at grab-thread start, so a burst
    inherits the preview's ROI timing: run 2026-08-13-09-18-35 delivered
    correct 320x64 frames at the 320x120 period, 1798 fps instead of 2624."""
    worker, cam = _worker(tmp_path)
    cam.open(1)
    cam.configure(CaptureConfig(320, 240, 500.0))     # a stale preview config
    cam.start()
    worker.capture_piston(CFG, duration_s=10.0)
    assert (cam.configs[-1].width, cam.configs[-1].height) == (320, 120)


def test_the_camera_is_stopped_before_it_is_reprogrammed(tmp_path):
    """A camera that is still grabbing ignores the new ROI, which is how a
    burst ends up with the previous frame period. Stop, program, restart."""

    class Recorder(FakeCamera):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.calls = []

        def stop(self):
            self.calls.append("stop")
            super().stop()

        def configure(self, cfg):
            self.calls.append("configure")
            super().configure(cfg)

        def start(self):
            self.calls.append("start")
            super().start()

    cam = Recorder(BURST)
    worker = CameraWorker(cam, EventBus(), tmp_path / "captures")
    worker.capture_piston(CFG, duration_s=10.0)
    assert cam.calls[:3] == ["stop", "configure", "start"]


def test_the_camera_is_opened_once_not_once_per_burst(tmp_path):
    """ImvCamera.open builds a NEW handle every call and never closes the old
    one, so opening per burst would leak handle #1 and let the SDK refuse the
    second burst of the process. Tk opened once per camera-thread lifetime;
    the web backend serves many runs from one long-lived process."""

    class OpensOnce(FakeCamera):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.opens = 0

        def open(self, index):
            self.opens += 1
            if self.opens > 1:
                raise CameraError("the camera is already open")
            super().open(index)

        def rewind(self):                       # replay the fixture again
            self._index = 0

    cam = OpensOnce(BURST)
    worker = CameraWorker(cam, EventBus(), tmp_path / "captures")
    first = worker.capture_piston(CFG, duration_s=10.0)
    cam.rewind()
    second = worker.capture_piston(CFG, duration_s=10.0)
    assert cam.opens == 1
    assert first.frames == second.frames == 12
    assert first.output_dir != second.output_dir


def test_a_frame_of_the_wrong_size_aborts_the_burst(tmp_path):
    """mm/px is calibrated at one ROI; a burst at another would be measured
    against the wrong magnification, so refuse rather than report wrong mm."""
    worker, _cam = _worker(tmp_path, roi_override=(320, 240))
    with pytest.raises(WrongFrameSize, match="320x240"):
        worker.capture_piston(CFG, duration_s=10.0)


def test_timing_file_records_ticks_relative_to_the_first_frame(tmp_path):
    from hsc import piston_track
    worker, _cam = _worker(tmp_path, fps=1000.0)
    result = worker.capture_piston(CFG, duration_s=10.0)
    meta = json.loads(
        (result.output_dir / piston_track.CAPTURE_META_NAME
         ).read_text(encoding="utf-8"))
    assert meta["frame_times_us"][0] == 0
    assert meta["frame_times_us"][1] == 1_000_000      # raw ticks, not converted
    assert meta["captured"] == 12
    assert meta["fps"] == pytest.approx(result.fps)


def test_dropped_frames_are_counted_from_block_id_gaps(tmp_path):
    bus = EventBus()
    worker, _cam = _worker(tmp_path, bus=bus, drop_after=3)
    q = bus.subscribe()
    result = worker.capture_piston(CFG, duration_s=10.0)
    assert result.dropped == 1
    # The Tk build printed "[Piston warning] N frame(s) dropped"; the operator
    # can only still be told if the count actually rides on the event.
    assert _payloads(q)["capture_done"]["dropped"] == 1


def test_a_burst_that_ended_early_is_flagged_as_truncated(tmp_path):
    """The camera stopped delivering before the burst was over. elapsed is
    measured to the break, so fps still reads ~1048 and the metadata is short
    but internally consistent -- a stroke truncated mid-travel would otherwise
    yield a plausible, quietly low peak speed. Say so instead."""
    from hsc import piston_track
    bus = EventBus()
    worker, _cam = _worker(tmp_path, bus=bus)          # 12 frames, 10 s asked
    q = bus.subscribe()
    result = worker.capture_piston(CFG, duration_s=10.0)
    meta = json.loads(
        (result.output_dir / piston_track.CAPTURE_META_NAME
         ).read_text(encoding="utf-8"))
    assert result.truncated is True
    assert meta["truncated"] is True
    assert _payloads(q)["capture_done"]["truncated"] is True


def test_a_one_frame_burst_still_writes_usable_timing(tmp_path):
    """Stop pressed the instant the burst starts: one frame is not a speed
    curve, but the folder must still be a complete, readable run."""
    from hsc import piston_track
    worker, _cam = _worker(tmp_path)
    seen = {"n": 0}

    def cancel():
        seen["n"] += 1
        return seen["n"] > 1

    result = worker.capture_piston(CFG, duration_s=10.0, cancel=cancel)
    meta = json.loads(
        (result.output_dir / piston_track.CAPTURE_META_NAME
         ).read_text(encoding="utf-8"))
    assert result.frames == 1
    assert result.dropped == 0
    assert meta["frame_times_us"] == [0]


def test_run_folder_carries_the_label_and_size(tmp_path):
    worker, _cam = _worker(tmp_path)
    result = worker.capture_piston(CFG, duration_s=10.0, label="IN37 30U")
    assert result.output_dir.name.endswith("_320x120_IN37-30U")


def test_cancel_stops_the_burst_and_keeps_what_was_grabbed(tmp_path):
    worker, _cam = _worker(tmp_path)
    stop_after = {"n": 0}

    def cancel():
        stop_after["n"] += 1
        return stop_after["n"] > 4

    result = worker.capture_piston(CFG, duration_s=10.0, cancel=cancel)
    assert 0 < result.frames < 12
    assert len(list(result.output_dir.glob("frame_*.bmp"))) == result.frames
    # The operator stopped it: a short burst, but not a camera that failed.
    assert result.truncated is False


def test_a_burst_that_grabbed_nothing_is_an_error(tmp_path):
    worker, _cam = _worker(tmp_path)
    with pytest.raises(RuntimeError, match="No frames"):
        worker.capture_piston(CFG, duration_s=10.0, cancel=lambda: True)


def test_sdk_runtime_errors_are_normalised_to_camera_error(tmp_path):
    """ImvCamera reports SDK failures as plain RuntimeError; every layer above
    this one should only ever have to catch CameraError."""

    class Broken(FakeCamera):
        def grab(self, timeout_ms):
            raise RuntimeError("IMV_GetFrame returned -101")

    worker = CameraWorker(Broken(BURST), EventBus(), tmp_path / "captures")
    with pytest.raises(CameraError, match="IMV_GetFrame returned -101"):
        worker.capture_piston(CFG, duration_s=10.0)


def test_a_camera_error_is_passed_through_unchanged(tmp_path):
    """FakeCamera (and the hardware seam's own checks) already raise the right
    type -- rewrapping would bury the message the operator needs."""

    class Broken(FakeCamera):
        def grab(self, timeout_ms):
            raise CameraError("the camera is not grabbing")

    worker = CameraWorker(Broken(BURST), EventBus(), tmp_path / "captures")
    with pytest.raises(CameraError) as excinfo:
        worker.capture_piston(CFG, duration_s=10.0)
    assert str(excinfo.value) == "the camera is not grabbing"


def test_progress_and_completion_are_published(tmp_path):
    """The payload is the whole point: it is what a UI has instead of the Tk
    build's status lines, so assert its contents, not just the event kinds."""
    bus = EventBus()
    worker = CameraWorker(FakeCamera(BURST), bus, tmp_path / "captures")
    q = bus.subscribe()
    result = worker.capture_piston(CFG, duration_s=10.0)
    seen = _payloads(q)
    assert set(seen) == {"capture_started", "capture_done"}
    assert seen["capture_started"] == {
        "output_dir": str(result.output_dir),
        "duration_s": 10.0,
        "size": "320x120",
    }
    assert seen["capture_done"] == {
        "output_dir": str(result.output_dir),
        "frames": 12,
        "fps": result.fps,
        "dropped": 0,
        "truncated": True,          # the fixture is shorter than the burst
    }
