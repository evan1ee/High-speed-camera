#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Pipeline jobs with phases, plus the same steps standalone for re-analysis."""
import shutil
import threading
from pathlib import Path

import pytest

from hsc.hardware.device import CaptureConfig
from hsc.hardware.fake import FakeCamera
from hsc.rig.events import EventBus
from hsc.rig.jobs import JobCancelled, JobManager, RigPaths
from hsc.rig.store import RunStore
from hsc.rig.worker import CameraWorker

BURST = Path(__file__).resolve().parents[1] / "fixtures" / "burst_320x120"
CFG = dict(width=320, height=120, exposure_us=500.0, duration_s=10.0)


def _paths(tmp_path):
    return RigPaths(captures=tmp_path / "captures",
                    injections=tmp_path / "injection images",
                    measures=tmp_path / "measure")


def _manager(tmp_path, camera=None, **cam):
    paths = _paths(tmp_path)
    worker = CameraWorker(camera or FakeCamera(BURST, **cam), EventBus(),
                          paths.captures)
    bus = EventBus()
    return JobManager(worker, RunStore(tmp_path / "rig.db"), bus, paths), bus


def _frames_copy(tmp_path, name):
    """A writable copy of the fixture -- make_video writes into its source."""
    dest = tmp_path / name
    shutil.copytree(BURST, dest)
    return dest


def test_capture_step_job_completes_and_reports_its_folder(tmp_path):
    manager, _bus = _manager(tmp_path)
    job_id = manager.submit("capture", CFG)
    job = manager.wait(job_id, timeout=30)
    assert job.state == "done"
    assert Path(job.result["output_dir"]).exists()


def test_unknown_job_kind_is_rejected(tmp_path):
    manager, _bus = _manager(tmp_path)
    with pytest.raises(ValueError, match="unknown job kind"):
        manager.submit("teleport", {})


def test_pipeline_emits_each_phase_in_order(tmp_path):
    manager, bus = _manager(tmp_path)
    q = bus.subscribe()
    job_id = manager.submit("piston_run", CFG)
    manager.wait(job_id, timeout=60)
    phases = [e.payload["phase"] for e in _drain(q)
              if e.kind == "job" and e.payload.get("phase")]
    assert phases[:1] == ["capture"]
    assert set(phases) <= {"capture", "find", "measure", "video"}


def test_pipeline_failure_stops_the_chain_and_records_the_reason(tmp_path):
    """The 12-frame fixture holds no stroke, so `find` must fail -- and the
    chain must not go on to measure a window that does not exist."""
    manager, bus = _manager(tmp_path)
    q = bus.subscribe()
    job = manager.wait(manager.submit("piston_run", CFG), timeout=60)
    assert job.state == "failed"
    # piston_track's own words, carried through unaltered: the operator needs
    # the reason it gave, not a phase name.
    assert "no piston movement" in job.error.lower()
    assert job.phase == "find"
    phases = [e.payload["phase"] for e in _drain(q)
              if e.kind == "job" and e.payload.get("phase")]
    assert "measure" not in phases


def test_cancel_marks_the_job_cancelled(tmp_path):
    manager, _bus = _manager(tmp_path)
    job_id = manager.submit("piston_run", dict(CFG, duration_s=30.0))
    manager.cancel(job_id)
    job = manager.wait(job_id, timeout=30)
    assert job.state == "cancelled"


def test_cancelling_a_running_capture_is_cancelled_not_failed(tmp_path):
    """Cancelling mid-burst, held still by the camera so the test creates the
    state instead of racing for it. The burst then ends with frames in hand,
    which is a different unwind than a cancel that lands before the first
    grab -- and a stopped burst is not a failure."""
    cam = _GatedCamera(BURST)
    manager, _bus = _manager(tmp_path, camera=cam)
    job_id = manager.submit("piston_run", CFG)
    assert cam.grabbing.wait(10)                  # the burst is under way
    manager.cancel(job_id)
    cam.gate.set()
    job = manager.wait(job_id, timeout=30)
    assert job.state == "cancelled"
    assert job.phase == "capture"
    assert job.error is None


def test_cancelling_an_unknown_job_returns_false(tmp_path):
    manager, _bus = _manager(tmp_path)
    assert manager.cancel("nope") is False


def test_get_returns_none_for_an_unknown_job(tmp_path):
    manager, _bus = _manager(tmp_path)
    assert manager.get("nope") is None


def test_waiting_on_an_unknown_job_returns_none(tmp_path):
    manager, _bus = _manager(tmp_path)
    assert manager.wait("nope", timeout=1) is None


def test_video_step_runs_standalone_on_an_existing_folder(tmp_path):
    """Re-analysis without the camera: the daily reason the steps exist alone."""
    folder = _frames_copy(tmp_path, "measured")
    manager, _bus = _manager(tmp_path)
    job = manager.wait(manager.submit("video", {"measure_dir": str(folder)}),
                       timeout=60)
    assert job.state == "done"
    assert Path(job.result["video"]).exists()
    assert job.progress == 1.0


def test_find_step_runs_standalone_and_reports_its_failure(tmp_path):
    manager, _bus = _manager(tmp_path)
    job = manager.wait(manager.submit("find", {"source_dir": str(BURST)}),
                       timeout=60)
    assert job.state == "failed"
    assert job.phase == "find"
    assert "no piston movement" in job.error.lower()


def test_measure_step_runs_standalone_and_reports_its_failure(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    manager, _bus = _manager(tmp_path)
    job = manager.wait(
        manager.submit("measure", {"injection_dir": str(empty)}), timeout=60)
    assert job.state == "failed"
    assert job.phase == "measure"
    assert "no image frames" in job.error.lower()


def test_progress_reports_and_becomes_the_cancellation_checkpoint(tmp_path):
    """The callback every long hsc/ operation already takes is where a job
    notices it was cancelled. Driven directly: interrupting a real step would
    mean racing it, and the seam is what matters."""
    manager, _bus = _manager(tmp_path)
    job_id = manager.submit("capture", CFG)
    job = manager.wait(job_id, timeout=30)
    report = manager._progress(job)
    report(1, 4)
    assert job.progress == 0.25
    report(0, 0)                       # a step with nothing to do: not a crash
    assert job.progress == 0.0
    manager.cancel(job_id)
    with pytest.raises(JobCancelled):
        report(2, 4)


def test_close_releases_the_camera(tmp_path):
    """CameraWorker deliberately never closes the device -- it cannot know when
    the process is done with it. This layer owns that, so the device does not
    stay open after the manager is finished with."""
    cam = _CountingCamera(BURST)
    manager, _bus = _manager(tmp_path, camera=cam)
    manager.wait(manager.submit("capture", CFG), timeout=30)
    manager.close()
    assert cam.closes == 1
    manager.close()                    # idempotent: the second is a no-op
    assert cam.closes == 1


def test_close_cancels_a_job_still_running(tmp_path):
    """Shutting down must not close the device out from under a live burst."""
    cam = _GatedCamera(BURST)
    manager, _bus = _manager(tmp_path, camera=cam)
    job_id = manager.submit("piston_run", CFG)
    assert cam.grabbing.wait(10)
    cam.gate.set()
    manager.close()
    assert cam.closes == 1
    assert manager.get(job_id).state == "cancelled"


def test_close_without_a_capture_leaves_the_camera_alone(tmp_path):
    cam = _CountingCamera(BURST)
    manager, _bus = _manager(tmp_path, camera=cam)
    manager.close()
    assert cam.closes == 0             # never opened, nothing to close


class _CountingCamera(FakeCamera):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closes = 0

    def close(self):
        self.closes += 1
        super().close()


class _GatedCamera(_CountingCamera):
    """Holds the burst still inside grab() until the test releases it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grabbing = threading.Event()
        self.gate = threading.Event()

    def grab(self, timeout_ms):
        self.grabbing.set()
        self.gate.wait(10)
        return super().grab(timeout_ms)


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out
