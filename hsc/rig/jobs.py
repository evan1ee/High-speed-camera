#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Jobs: one pipeline that chains the piston workflow, and the same steps
standalone.

The chain mirrors what the Tk app did (capture -> find -> measure -> video),
because that is the workflow the rig is operated with. The steps are also
available alone, because re-measuring an existing folder without re-capturing
is a daily operation.

Cancellation reuses something that already exists: every long operation in
``hsc/`` takes a ``progress(done, total)`` callback, so that is where a job
checks whether it has been cancelled. No analysis module needs to change.
"""

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from hsc import make_video, measure_piston, piston_track
from hsc.hardware.device import CaptureConfig
from hsc.rig.store import RunRecord

PIPELINE_PHASES = ("capture", "find", "measure", "video")

#: Padding around the detected stroke, as the Tk build used everywhere.
PAD_BEFORE = 30
PAD_AFTER = 30


class JobCancelled(RuntimeError):
    """Raised inside a progress callback to unwind a cancelled job."""


@dataclass
class RigPaths:
    captures: Path
    injections: Path
    measures: Path


@dataclass
class Job:
    id: str
    kind: str
    params: dict
    state: str = "queued"
    phase: str | None = None
    progress: float = 0.0
    error: str | None = None
    run_id: int | None = None
    result: dict = field(default_factory=dict)


class JobManager:
    """Runs one job per thread and owns the camera worker's lifetime."""

    def __init__(self, worker, store, bus, paths):
        self._worker = worker
        self._store = store
        self._bus = bus
        self._paths = paths
        self._jobs = {}
        self._cancels = {}
        self._threads = {}
        self._guard = threading.Lock()

    # -- public ------------------------------------------------------------
    def submit(self, kind, params):
        if kind not in _RUNNERS:
            raise ValueError(f"unknown job kind: {kind}")
        job = Job(id=uuid.uuid4().hex, kind=kind, params=dict(params))
        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        with self._guard:
            self._jobs[job.id] = job
            self._cancels[job.id] = threading.Event()
            self._threads[job.id] = thread
        thread.start()
        return job.id

    def get(self, job_id):
        with self._guard:
            return self._jobs.get(job_id)

    def cancel(self, job_id):
        with self._guard:
            event = self._cancels.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def wait(self, job_id, timeout=60):
        with self._guard:
            thread = self._threads.get(job_id)
        if thread is not None:
            thread.join(timeout)
        return self.get(job_id)

    def close(self, timeout=30):
        """Stop everything and release the camera.

        ``CameraWorker`` opens the device once and never closes it -- it cannot
        know when the process is finished with it, and closing per burst would
        cost the next run its handle. This layer does know, so shutdown belongs
        here. Jobs are cancelled and joined FIRST: closing the device while the
        grab loop still holds it is how an SDK is left in a state the next
        process cannot open.
        """
        with self._guard:
            events = list(self._cancels.values())
            threads = list(self._threads.values())
        for event in events:
            event.set()
        for thread in threads:
            thread.join(timeout)
        self._worker.close()

    # -- internals ---------------------------------------------------------
    def _run(self, job):
        self._set(job, state="running")
        try:
            _RUNNERS[job.kind](self, job)
            self._set(job, state="done", progress=1.0)
        except JobCancelled:
            self._set(job, state="cancelled")
        except Exception as exc:
            # ``phase`` is left where it failed: which step broke is half the
            # report, and the message is the analysis module's own words.
            self._set(job, state="failed", error=str(exc))

    def _set(self, job, **changes):
        for key, value in changes.items():
            setattr(job, key, value)
        # ``job_kind``, not ``kind``: the event's own kind is the publisher's
        # first argument, so a payload key of that name collides with it.
        self._bus.publish("job", id=job.id, job_kind=job.kind, state=job.state,
                          phase=job.phase, progress=job.progress,
                          error=job.error, run_id=job.run_id)

    def _cancelled(self, job):
        return self._cancels[job.id].is_set()

    def _progress(self, job):
        """The callback handed to every long ``hsc/`` step: it reports, and it
        is the one place a running analysis notices it was cancelled."""
        def report(done, total):
            if self._cancelled(job):
                raise JobCancelled()
            job.progress = (done / total) if total else 0.0
        return report

    def _config(self, job):
        params = job.params
        return CaptureConfig(width=int(params["width"]),
                             height=int(params["height"]),
                             exposure_us=float(params["exposure_us"]))

    # -- steps -------------------------------------------------------------
    def _capture(self, job):
        self._set(job, phase="capture")
        # Bound method, not a lambda around a dict lookup: the grab loop calls
        # this once per frame, up to ~1798 times a second.
        stopped = self._cancels[job.id].is_set
        try:
            result = self._worker.capture_piston(
                self._config(job), float(job.params.get("duration_s", 4.0)),
                label=job.params.get("label", ""), cancel=stopped)
        except Exception:
            # A burst stopped before its first frame raises ("No frames were
            # grabbed") -- true of the camera, wrong about the job. The
            # operator cancelled it; report cancelled, not failed.
            if stopped():
                raise JobCancelled() from None
            raise
        if stopped():
            raise JobCancelled()
        job.result["output_dir"] = str(result.output_dir)
        return result.output_dir

    def _find(self, job, source_dir):
        self._set(job, phase="find")
        found = piston_track.extract_piston_event(
            source_dir, dest_base=self._paths.injections,
            before=PAD_BEFORE, after=PAD_AFTER, fast=True,
            progress=self._progress(job))
        job.result["injection_dir"] = found["dest_dir"]
        return Path(found["dest_dir"])

    def _measure(self, job, injection_dir):
        self._set(job, phase="measure")
        result = measure_piston.measure_folder(
            injection_dir, dest_base=self._paths.measures,
            progress=self._progress(job),
            log=lambda text: self._bus.publish("log", text=text))
        job.result["measure_dir"] = result["dest_dir"]
        job.run_id = self._store.add_run(_record_from(result, job))
        return Path(result["dest_dir"])

    def _video(self, job, measure_dir):
        self._set(job, phase="video")
        made = make_video.make_video(measure_dir, progress=self._progress(job))
        job.result["video"] = made["out_path"]


def _capture_only(manager, job):
    manager._capture(job)


def _find_only(manager, job):
    manager._find(job, Path(job.params["source_dir"]))


def _measure_only(manager, job):
    manager._measure(job, Path(job.params["injection_dir"]))


def _video_only(manager, job):
    manager._video(job, Path(job.params["measure_dir"]))


def _pipeline(manager, job):
    source = manager._capture(job)
    injection = manager._find(job, source)
    measure = manager._measure(job, injection)
    manager._video(job, measure)


_RUNNERS = {
    "capture": _capture_only,
    "find": _find_only,
    "measure": _measure_only,
    "video": _video_only,
    "piston_run": _pipeline,
}


def _record_from(result, job):
    return RunRecord(
        kind="piston",
        captured_at=str(job.params.get("captured_at", "")),
        measure_dir=result["dest_dir"],
        label=job.params.get("label") or None,
        source_dir=job.result.get("output_dir"),
        injection_dir=job.result.get("injection_dir"),
        roi=f"{job.params.get('width')}x{job.params.get('height')}",
        fps=result.get("fps"), timebase=result.get("timebase"),
        exposure_us=job.params.get("exposure_us"),
        mm_per_px=result.get("mm_per_px"),
        scale_source=result.get("scale_source"),
        stroke_px=result.get("stroke_px"), stroke_mm=result.get("stroke_mm"),
        duration_ms=result.get("duration_ms"),
        mean_speed_mm_s=result.get("mean_speed_mm_s"),
        peak_speed_mm_s=result.get("peak_speed_mm_s"),
        peak_jet_speed_m_s=result.get("peak_jet_speed_m_s"),
        peak_jet_pressure_MPa=result.get("peak_jet_pressure_MPa"),
        measured_count=result.get("measured_count"))
