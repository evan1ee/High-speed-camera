#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The whole pipeline against a fake camera: capture, find, measure, persist.

This is the first coverage the capture path has ever had end to end.
"""
from pathlib import Path

import pytest

from hsc.hardware.fake import FakeCamera
from hsc.rig.events import EventBus
from hsc.rig.jobs import JobManager, RigPaths
from hsc.rig.store import RunStore
from hsc.rig.worker import CameraWorker

PARAMS = dict(width=320, height=240, exposure_us=500.0, duration_s=60.0,
              label="TEST-4U")


def _manager(tmp_path, burst):
    paths = RigPaths(captures=tmp_path / "captures",
                     injections=tmp_path / "injection images",
                     measures=tmp_path / "measure")
    store = RunStore(tmp_path / "rig.db")
    bus = EventBus()
    worker = CameraWorker(FakeCamera(burst, fps=1000.0), bus, paths.captures)
    return JobManager(worker, store, bus, paths), store, bus


def test_pipeline_measures_and_persists_a_run(tmp_path, synthetic_burst):
    manager, store, bus = _manager(tmp_path, synthetic_burst)
    q = bus.subscribe()

    job = manager.wait(manager.submit("piston_run", PARAMS), timeout=300)

    assert job.state == "done", job.error
    assert job.run_id is not None

    phases = [e.payload["phase"] for e in _drain(q)
              if e.kind == "job" and e.payload.get("phase")]
    assert _first_seen(phases) == ["capture", "find", "measure", "video"]

    run = store.get_run(job.run_id)
    assert run.kind == "piston"
    assert run.label == "TEST-4U"
    # 120 frames x 1.2 px at the synthetic scale; the exact mm depend on the
    # stored calibration, so assert the px stroke which does not.
    assert run.stroke_px == pytest.approx(144.0, rel=0.05)
    assert Path(run.measure_dir).exists()
    assert list(Path(run.measure_dir).glob("*_speed.csv"))
    assert Path(job.result["video"]).exists()


def test_measure_step_can_be_rerun_standalone(tmp_path, synthetic_burst):
    """Re-measuring an existing folder without re-capturing is a daily task."""
    manager, store, _bus = _manager(tmp_path, synthetic_burst)
    first = manager.wait(manager.submit("piston_run", PARAMS), timeout=300)
    assert first.state == "done", first.error

    again = manager.wait(manager.submit(
        "measure", {"injection_dir": first.result["injection_dir"],
                    "width": 320, "height": 240}), timeout=300)

    assert again.state == "done", again.error
    assert len(store.list_runs()) == 2      # a second measure folder


def _first_seen(phases):
    seen = []
    for phase in phases:
        if phase not in seen:
            seen.append(phase)
    return seen


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out
