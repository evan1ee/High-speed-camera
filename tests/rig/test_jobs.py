#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Pipeline jobs with phases, plus the same steps standalone for re-analysis."""
import shutil
import threading
from pathlib import Path

import pytest

from hsc.hardware.device import CameraError, CaptureConfig
from hsc.hardware.fake import FakeCamera
from hsc.rig import jobs as jobs_module
from hsc.rig.events import EventBus
from hsc.rig.jobs import Job, JobCancelled, JobManager, RigBusy, RigPaths
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


def test_a_camera_fault_fails_the_job_and_is_not_read_as_a_cancel(tmp_path):
    """The cancel path forgives the burst's own error, so a burst that broke
    for a real reason must not be quietly relabelled as an operator stop."""
    manager, _bus = _manager(tmp_path, roi_override=(320, 240))
    job = manager.wait(manager.submit("piston_run", CFG), timeout=30)
    assert job.state == "failed"
    assert job.phase == "capture"
    assert "320x240" in job.error


def test_a_fault_while_cancelling_still_fails_the_job(tmp_path):
    """The cancel unwind forgives exactly one thing: a burst that stopped
    before its first frame. A burst that broke while WRITING must stay a
    failure -- the flag is set for the whole unwind, and `capture_piston`
    saves every frame after the loop ends, so reporting "cancelled" there
    would tell the operator the run was stopped when the frames were in fact
    never written."""
    cam = _GatedCamera(BURST, save_error="the disk is full")
    manager, _bus = _manager(tmp_path, camera=cam)
    job_id = manager.submit("piston_run", CFG)
    assert cam.grabbing.wait(10)
    manager.cancel(job_id)                        # cancelling AND breaking
    cam.gate.set()
    job = manager.wait(job_id, timeout=30)
    assert job.state == "failed"
    assert "the disk is full" in job.error


def test_a_burst_that_grabbed_nothing_fails_when_nobody_cancelled(tmp_path):
    """Same exception, opposite verdict: with no cancel behind it, an empty
    burst is a camera that delivered nothing, and the operator needs to be
    told that rather than see a job quietly marked stopped."""
    manager, _bus = _manager(tmp_path, camera=_SilentCamera(BURST))
    job = manager.wait(manager.submit("capture", CFG), timeout=30)
    assert job.state == "failed"
    assert "No frames were grabbed" in job.error


def test_a_second_camera_job_is_refused_while_one_owns_the_camera(tmp_path):
    """Two bursts on one handle interleave stop/configure/start: job B's stop
    makes job A's grab return None, and A is written out as a quietly
    truncated stroke with a plausible, low peak speed. The Tk app refused
    this; so does this one."""
    cam = _GatedCamera(BURST)
    manager, _bus = _manager(tmp_path, camera=cam)
    job_id = manager.submit("piston_run", CFG)
    assert cam.grabbing.wait(10)
    with pytest.raises(RigBusy, match="camera"):
        manager.submit("capture", CFG)
    manager.cancel(job_id)
    cam.gate.set()
    manager.wait(job_id, timeout=30)
    second = manager.submit("capture", CFG)       # the camera is free again
    manager.wait(second, timeout=30)


def test_re_analysis_is_not_blocked_by_a_running_capture(tmp_path):
    """find/measure/video touch no camera, and re-measuring an existing folder
    while the rig captures is a daily operation."""
    folder = _frames_copy(tmp_path, "measured")
    cam = _GatedCamera(BURST)
    manager, _bus = _manager(tmp_path, camera=cam)
    capture_id = manager.submit("piston_run", CFG)
    assert cam.grabbing.wait(10)
    video = manager.wait(manager.submit("video", {"measure_dir": str(folder)}),
                         timeout=60)
    assert video.state == "done"
    manager.cancel(capture_id)
    cam.gate.set()
    manager.wait(capture_id, timeout=30)


def test_the_persisted_row_matches_what_the_importer_would_read(tmp_path):
    """The importer re-reads this same folder at every restart and upserts on
    measure_dir, so a column filled there and left empty here makes the run
    change the moment the service is restarted."""
    measure_dir = tmp_path / "piston_2026-08-14-14-28-09_320x120_IN37-30U"
    measure_dir.mkdir()
    csv_path = measure_dir / f"{measure_dir.name}_speed.csv"
    csv_path.write_text("unstable_frames,3\n", encoding="utf-8")
    job = Job(id="j", kind="piston_run", params=dict(CFG, label="IN37 30U"))
    record = jobs_module._record_from(
        {"dest_dir": str(measure_dir), "csv_path": str(csv_path),
         "barrel_mm": 6.0, "orifice_mm": 0.17, "fluid_density": 1000.0,
         "measured_count": 120, "peak_speed_mm_s": 131.1}, job)
    assert record.captured_at == "2026-08-14T14:28:09"     # not ""
    assert record.roi == "320x120"
    assert (record.barrel_mm, record.orifice_mm, record.density) == (
        6.0, 0.17, 1000.0)
    assert record.unstable_frames == 3
    assert record.label == "IN37 30U"


def test_the_capture_warnings_reach_the_run_row(tmp_path):
    """A truncated or lossy burst is NOT self-evident downstream: elapsed is
    measured to the break, so fps still reads ~1048 and detect_piston_bounds
    scales off the travel it can see -- a shortened stroke with a plausible,
    quietly low peak speed. The flag was a transient capture_done event a tab
    connecting later never saw; the run row is where it has to live."""
    measure_dir = tmp_path / "piston_2026-08-14-14-28-09_320x120"
    measure_dir.mkdir()
    job = Job(id="j", kind="piston_run", params=CFG)
    job.result.update(truncated=True, dropped=2)
    record = jobs_module._record_from({"dest_dir": str(measure_dir)}, job)
    assert record.truncated == 1          # SQLite has no boolean
    assert record.dropped == 2


def test_a_burst_that_ran_to_time_says_so_rather_than_nothing(tmp_path):
    measure_dir = tmp_path / "piston_2026-08-14-14-28-09_320x120"
    measure_dir.mkdir()
    job = Job(id="j", kind="piston_run", params=CFG)
    job.result.update(truncated=False, dropped=0)
    record = jobs_module._record_from({"dest_dir": str(measure_dir)}, job)
    assert record.truncated == 0
    assert record.dropped == 0


def test_a_capture_job_records_the_warnings_on_the_job(tmp_path):
    """End to end on the real seam: the 12-frame fixture cannot fill a 10 s
    burst, so the camera stops delivering and the burst is truncated."""
    manager, _bus = _manager(tmp_path)
    job = manager.wait(manager.submit("capture", CFG), timeout=30)
    assert job.state == "done"
    assert job.result["truncated"] is True
    assert job.result["dropped"] == 0


def test_a_standalone_measure_row_invents_no_roi(tmp_path):
    """Re-analysis carries no capture settings, and an ROI built from two
    missing params would store the literal "NonexNone" as fact."""
    measure_dir = tmp_path / "hand-named-folder"
    measure_dir.mkdir()
    job = Job(id="j", kind="measure",
              params={"injection_dir": "x", "captured_at": "2026-08-14T09:00:00"})
    record = jobs_module._record_from({"dest_dir": str(measure_dir)}, job)
    assert record.roi is None
    assert record.captured_at == "2026-08-14T09:00:00"     # the caller's value
    assert record.unstable_frames is None                  # no CSV to read
    # Nobody captured anything here, and "nobody looked" must not be stored as
    # "the burst was fine".
    assert record.truncated is None and record.dropped is None


def test_an_unreadable_csv_does_not_lose_the_finished_measurement(tmp_path):
    """The measurement is already on disk; one unreadable column must not
    throw away the row that describes it."""
    measure_dir = tmp_path / "piston_2026-08-14-14-28-09_320x120"
    measure_dir.mkdir()
    job = Job(id="j", kind="piston_run", params=CFG)
    record = jobs_module._record_from(
        {"dest_dir": str(measure_dir),
         "csv_path": str(measure_dir / "gone.csv")}, job)
    assert record.unstable_frames is None
    assert record.captured_at == "2026-08-14T14:28:09"


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


def test_close_refuses_to_close_the_device_under_a_running_job(tmp_path):
    """Cancelling breaks the GRAB loop only -- capture_piston then saves every
    clone one file at a time, so a burst outliving the join is routine.
    Closing the handle there is how the SDK is left in a state the next
    process cannot open, so it must be reported and skipped, not done anyway.
    """
    cam = _GatedCamera(BURST)
    manager, bus = _manager(tmp_path, camera=cam)
    q = bus.subscribe()
    job_id = manager.submit("piston_run", CFG)
    assert cam.grabbing.wait(10)                  # held inside grab()

    still_running = manager.close(timeout=0.1)

    assert still_running == [job_id]
    assert cam.closes == 0                        # the device was left alone
    logged = [e.payload["text"] for e in _drain(q) if e.kind == "log"]
    assert any("NOT closed" in text and job_id in text for text in logged)
    cam.gate.set()                                # let the burst unwind
    manager.wait(job_id, timeout=30)


def test_close_reports_nothing_when_every_job_finished(tmp_path):
    cam = _CountingCamera(BURST)
    manager, _bus = _manager(tmp_path, camera=cam)
    manager.wait(manager.submit("capture", CFG), timeout=30)
    assert manager.close() == []
    assert cam.closes == 1


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


class _SilentCamera(FakeCamera):
    """Opens and starts, then never delivers a frame."""

    def grab(self, timeout_ms):
        return None


class _GatedCamera(_CountingCamera):
    """Holds the burst still inside grab() until the test releases it, and can
    break on the way out (``save_error``) the way a full disk would."""

    def __init__(self, *args, save_error=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.grabbing = threading.Event()
        self.gate = threading.Event()
        self.save_error = save_error

    def grab(self, timeout_ms):
        self.grabbing.set()
        self.gate.wait(10)
        return super().grab(timeout_ms)

    def save(self, frame, path):
        if self.save_error is not None:
            raise CameraError(self.save_error)
        super().save(frame, path)


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out
