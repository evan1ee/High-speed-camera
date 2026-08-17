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

from hsc import capture_image, make_video, measure_piston, piston_track
from hsc.hardware.device import CaptureConfig
from hsc.rig import importer
from hsc.rig.store import RunRecord
from hsc.rig.worker import NoFramesGrabbed

PIPELINE_PHASES = ("capture", "find", "measure", "video")

#: Padding around the detected stroke, as the Tk build used everywhere.
PAD_BEFORE = 30
PAD_AFTER = 30

#: Job kinds that drive the camera. Only one may be active at a time: two
#: bursts share one handle, so B's ``stop -> configure -> start`` makes A's
#: ``grab`` return None mid-stroke, and A is written out as a quietly
#: truncated run -- a shortened stroke with a plausible, low peak speed. The
#: Tk app refused this outright; a lease does not cover it, because one holder
#: can post two jobs.
CAMERA_KINDS = frozenset({"capture", "piston_run"})

#: A job that has not finished, and so may still own the camera.
ACTIVE_STATES = frozenset({"queued", "running"})


class JobCancelled(RuntimeError):
    """Raised inside a progress callback to unwind a cancelled job."""


class RigBusy(RuntimeError):
    """A camera job was submitted while another one still owns the camera."""


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
            busy = self._camera_job() if kind in CAMERA_KINDS else None
            if busy is not None:
                raise RigBusy(
                    f"the camera is busy with job {busy.id} ({busy.kind}); "
                    "stop it before starting another")
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
        """Stop everything and release the camera. Returns the ids of the jobs
        that were still running when it gave up waiting -- empty when the
        device was closed cleanly.

        ``CameraWorker`` opens the device once and never closes it -- it cannot
        know when the process is finished with it, and closing per burst would
        cost the next run its handle. This layer does know, so shutdown belongs
        here. Jobs are cancelled and joined FIRST: closing the device while the
        grab loop still holds it is how an SDK is left in a state the next
        process cannot open.

        And when the join times out the device is NOT closed anyway, which is
        what this used to do. Exceeding the timeout is routine, not exotic:
        cancelling breaks the GRAB loop only, and ``capture_piston`` then saves
        every clone one file at a time -- a 10 s burst at 1798 fps is ~18 000
        BMPs, and ``duration_s`` is not validated. Leaving the handle open
        until the process exits costs the next process nothing it would not
        also lose to a half-closed device; closing under a live SDK call is the
        failure that needs a power cycle. Reported rather than raised: this
        runs from the app's shutdown ``finally``, and an exception there would
        bury whatever else went wrong.
        """
        with self._guard:
            events = list(self._cancels.values())
            threads = dict(self._threads)
        for event in events:
            event.set()
        for thread in threads.values():
            thread.join(timeout)
        alive = sorted(job_id for job_id, thread in threads.items()
                       if thread.is_alive())
        if alive:
            self._bus.publish("log", text=(
                f"The camera was NOT closed: job(s) {', '.join(alive)} are "
                f"still running after {timeout}s. Closing the device while a "
                f"job still holds it can leave the SDK unable to open it."))
            return alive
        self._worker.close()
        return []

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

    def _camera_job(self):
        """The unfinished job that owns the camera, if there is one. Call
        under the guard."""
        return next((job for job in self._jobs.values()
                     if job.kind in CAMERA_KINDS and job.state in ACTIVE_STATES),
                    None)

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
        except NoFramesGrabbed:
            # The ONE burst failure a cancel may forgive: stopped before the
            # first frame is what the operator asked for. Anything else --
            # including a write that broke in the save loop, which runs after
            # the cancel flag is already set -- stays a failure, or the
            # operator is told "cancelled" about frames that never reached the
            # disk. See worker.NoFramesGrabbed.
            if stopped():
                raise JobCancelled() from None
            raise
        if stopped():
            raise JobCancelled()
        job.result["output_dir"] = str(result.output_dir)
        # The burst's warnings ride on the job from here, and into the run row
        # in _record_from. Without that they existed only as a transient
        # ``capture_done`` event -- a tab that connects later never sees it,
        # and piston_meta.json is written by an analysis module this layer must
        # not change. See BurstResult.truncated for why silence is dangerous.
        job.result["truncated"] = result.truncated
        job.result["dropped"] = result.dropped
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
    """The database row for a finished measurement.

    Written to match what :mod:`hsc.rig.importer` reads back out of the same
    folder at the next restart -- it upserts on ``measure_dir``, so any column
    it fills and this one leaves empty makes the run change on restart.
    """
    dest = Path(result["dest_dir"])
    _kind, folder_stamp, folder_roi, _label = importer.parse_folder_name(
        dest.name)
    return RunRecord(
        kind="piston",
        # The run folder carries the capture's timestamp, and it is what the
        # importer will read. An empty string here would sort the run the
        # operator just made to the bottom of a `captured_at DESC` list.
        captured_at=folder_stamp or str(job.params.get("captured_at", "")),
        # Resolved, because measure_dir is the table's UNIQUE key and the
        # importer resolves too. Launched once with --data-root . and once with
        # the default absolute root, the same folder would otherwise be two
        # different strings and every run would DUPLICATE instead of upserting.
        measure_dir=str(dest.resolve()),
        # Sanitised, not raw: the folder name went through safe_label, which
        # folds whitespace to '-', so 'IN37 30U' comes back as 'IN37-30U' at
        # the next restart. Storing the raw form made the label -- and the
        # exact-match list_runs(label=...) filter -- change on restart.
        label=capture_image.safe_label(job.params.get("label", "")) or None,
        source_dir=job.result.get("output_dir"),
        injection_dir=job.result.get("injection_dir"),
        roi=_roi(job.params, folder_roi),
        fps=result.get("fps"), timebase=result.get("timebase"),
        exposure_us=job.params.get("exposure_us"),
        mm_per_px=result.get("mm_per_px"),
        scale_source=result.get("scale_source"),
        barrel_mm=result.get("barrel_mm"), orifice_mm=result.get("orifice_mm"),
        density=result.get("fluid_density"),
        stroke_px=result.get("stroke_px"), stroke_mm=result.get("stroke_mm"),
        duration_ms=result.get("duration_ms"),
        mean_speed_mm_s=result.get("mean_speed_mm_s"),
        peak_speed_mm_s=result.get("peak_speed_mm_s"),
        peak_jet_speed_m_s=result.get("peak_jet_speed_m_s"),
        peak_jet_pressure_MPa=result.get("peak_jet_pressure_MPa"),
        unstable_frames=_unstable_frames(result),
        measured_count=result.get("measured_count"),
        truncated=_flag(job.result.get("truncated")),
        dropped=job.result.get("dropped"))


def _flag(value):
    """A capture warning as SQLite stores it: 0/1, and ``None`` left alone.

    ``None`` is not ``False`` here -- a standalone measure job never captured
    anything, and "nobody looked" must not be read as "the burst was fine".
    """
    return None if value is None else int(value)


def _roi(params, folder_roi):
    """The capture ROI, or ``None`` -- never a string built out of blanks.

    A standalone ``measure`` job carries no capture settings, and
    ``f"{None}x{None}"`` would store the literal ``"NonexNone"`` for the runs
    list to show as fact.
    """
    width, height = params.get("width"), params.get("height")
    if width and height:
        return f"{width}x{height}"
    return folder_roi


def _unstable_frames(result):
    """The one column ``measure_folder`` writes but does not return.

    Read from the CSV summary block exactly as the importer reads it, so the
    row does not gain the number at the next restart. Unreadable ⇒ ``None``:
    the measurement is already on disk, and one missing column must not throw
    away the row that describes it.
    """
    csv_path = result.get("csv_path")
    if not csv_path:
        return None
    try:
        raw = importer._raw_summary_values(Path(csv_path), {"unstable_frames"})
    except OSError:
        return None
    return importer._to_int(raw.get("unstable_frames"))
