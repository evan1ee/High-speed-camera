#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The entry point: argument parsing and wiring, with no server bound.

``uvicorn.run`` is replaced everywhere below -- a test that opened a port
would be a test of the operating system, and would fail on a machine where
that port is taken. The real camera is replaced too: ``ImvCamera.__init__``
loads the SDK, which is not present without the rig.
"""

import runpy
from pathlib import Path

import pytest

from hsc.api import __main__ as entry

# One measured run, exactly as ``hsc.summary`` writes it, so the importer has
# something to find (copied from tests/rig/test_importer.py).
CSV = """frame,time_ms,x_px,distance_px,distance_mm,speed_mm_s,speed_m_s,k,n_points,rms_px,coverage,at_border,stable
frame_000001.bmp,0.000,117.0,0.000,0.0000,0.00,0.0000,-0.02,50,0.30,1.000,no,yes
frame_000002.bmp,0.575,117.6,0.600,0.0356,62.00,0.0620,-0.02,50,0.30,1.000,no,yes

unstable_frames,1
stroke_px,172.600
stroke_mm,10.2540
duration_ms,112.1000
mean_speed_mm_s,91.5000
peak_speed_mm_s,194.0000
fps,1738.7676
timebase,timestamps (ns)
reference_frame,frame_000001.bmp
"""


class StubCamera:
    """Stands in for ``ImvCamera``; the entry point only constructs it."""


@pytest.fixture(autouse=True)
def no_camera_and_no_server(monkeypatch):
    """Neither the SDK nor a socket is available in the test environment."""
    calls = []
    monkeypatch.setattr("hsc.hardware.imv.ImvCamera", StubCamera)
    monkeypatch.setattr(entry, "ImvCamera", StubCamera)
    monkeypatch.setattr("uvicorn.run",
                        lambda app, **kw: calls.append((app, kw)))
    return calls


def measured_run(root, name="piston_2026-08-14-14-28-09_320x120_IN37-30U"):
    folder = root / "measure" / name
    folder.mkdir(parents=True)
    (folder / f"{name}_speed.csv").write_text(CSV, encoding="utf-8")
    return name


def test_build_wires_the_whole_stack_under_the_given_data_root(tmp_path):
    app = entry.build(tmp_path)

    services = app.state.services
    assert services.paths.captures == tmp_path / "captures"
    assert services.paths.injections == tmp_path / "injection images"
    assert services.paths.measures == tmp_path / "measure"
    assert (tmp_path / "rig.db").exists()
    assert services.lease.holder is None
    assert services.spa_dir is None and services.cors_origins == ()


def test_build_imports_the_runs_already_on_disk(tmp_path):
    name = measured_run(tmp_path)

    app = entry.build(str(tmp_path))

    runs = app.state.services.store.list_runs()
    assert [Path(r.measure_dir).name for r in runs] == [name]
    assert runs[0].stroke_mm == 10.254


def test_build_passes_the_spa_directory_and_cors_origins_through(tmp_path):
    spa = tmp_path / "web"
    spa.mkdir()
    (spa / "index.html").write_text("<html></html>", encoding="utf-8")

    app = entry.build(tmp_path, spa=str(spa), cors=["http://rig.local"])

    assert app.state.services.spa_dir == spa
    assert app.state.services.cors_origins == ("http://rig.local",)


def test_build_falls_back_to_the_projects_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, "data_root", lambda: tmp_path)

    app = entry.build()

    assert app.state.services.paths.captures == tmp_path / "captures"


def test_main_serves_the_built_app_on_the_requested_address(
        tmp_path, monkeypatch, no_camera_and_no_server):
    spa = tmp_path / "web"
    spa.mkdir()
    monkeypatch.setattr("sys.argv", [
        "hsc.api", "--host", "100.64.0.7", "--port", "9001",
        "--data-root", str(tmp_path), "--spa", str(spa),
        "--cors", "http://a", "--cors", "http://b"])

    entry.main()

    (app, kwargs), = no_camera_and_no_server
    assert kwargs == {"host": "100.64.0.7", "port": 9001}
    assert app.state.services.spa_dir == spa
    assert app.state.services.cors_origins == ("http://a", "http://b")


def test_main_defaults_to_localhost_port_8000(
        tmp_path, monkeypatch, no_camera_and_no_server):
    monkeypatch.setattr(entry, "data_root", lambda: tmp_path)
    monkeypatch.setattr("sys.argv", ["hsc.api"])

    entry.main()

    (_, kwargs), = no_camera_and_no_server
    assert kwargs == {"host": "127.0.0.1", "port": 8000}


def test_running_the_module_as_a_script_calls_main(
        tmp_path, monkeypatch, no_camera_and_no_server):
    """``python -m hsc.api`` must actually start the service.

    Executed through ``runpy`` with ``run_name="__main__"`` so the guard at
    the bottom of the file is exercised the way the command line exercises it.
    """
    monkeypatch.setattr("sys.argv", ["hsc.api", "--data-root", str(tmp_path)])

    runpy.run_path(entry.__file__, run_name="__main__")

    (_, kwargs), = no_camera_and_no_server
    assert kwargs == {"host": "127.0.0.1", "port": 8000}
