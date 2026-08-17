#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Reading results: list, detail, the per-frame CSV, and media files.

The media route is the one place a client names a file on the rig's disk, so
most of what is asserted here is that a crafted name cannot reach one. The
escapes are spelled the Windows way as well as the POSIX way, because this
rig is Windows-only and ``..\\..\\`` is a traversal there while ``..%2F`` is
not even a single path segment.
"""
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

from hsc.rig.store import RunRecord

SUMMARY_CSV = ("frame,time_ms\n"
               "frame_000001.bmp,0.0\n"
               "\n"
               "stroke_mm,{stroke}\n"
               "peak_speed_mm_s,{peak}\n"
               "duration_ms,12.0\n")


def _add(services, tmp_path, name="piston_run", **over):
    folder = tmp_path / "measure" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}_speed.csv").write_text("frame,time_ms\na,1\n",
                                              encoding="utf-8")
    (folder / f"{name}_speed_time.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    record = RunRecord(kind="piston", captured_at="2026-08-14T10:00:00",
                       measure_dir=str(folder), label="L", stroke_mm=1.0)
    for key, value in over.items():
        setattr(record, key, value)
    return services.store.add_run(record)


def _measured(services, tmp_path, name, stroke, peak):
    """A run folder whose CSV really carries a summary block."""
    run_id = _add(services, tmp_path, name=name)
    folder = tmp_path / "measure" / name
    (folder / f"{name}_speed.csv").write_text(
        SUMMARY_CSV.format(stroke=stroke, peak=peak), encoding="utf-8")
    return run_id


def test_list_and_detail(client, services, tmp_path):
    run_id = _add(services, tmp_path)
    listed = client.get("/api/runs").json()
    assert listed[0]["id"] == run_id
    assert client.get(f"/api/runs/{run_id}").json()["label"] == "L"


def test_detail_404_for_unknown_run(client):
    assert client.get("/api/runs/999").status_code == 404


def test_the_run_payload_carries_the_captures_warnings(client, services,
                                                       tmp_path):
    """A truncated or lossy burst measures into a plausible, quietly low peak
    speed. The only place an operator can still learn it is the run itself --
    the capture_done event is long gone by the time anyone reads the result."""
    run_id = _add(services, tmp_path, name="short", truncated=1, dropped=7)
    payload = client.get(f"/api/runs/{run_id}").json()
    assert payload["truncated"] == 1
    assert payload["dropped"] == 7
    assert client.get("/api/runs").json()[0]["truncated"] == 1


def test_list_filters_by_kind_and_limit(client, services, tmp_path):
    _add(services, tmp_path, name="a")
    _add(services, tmp_path, name="b", kind="spray")
    assert len(client.get("/api/runs?kind=piston").json()) == 1
    assert len(client.get("/api/runs?limit=1").json()) == 1


@pytest.mark.parametrize("limit, why", [
    # SQLite reads a negative LIMIT as UNBOUNDED, so -1 does not clamp to a
    # small page, it returns the whole table and bypasses the default of 100.
    # A frontend computing a page size arithmetically can reach it by accident.
    pytest.param(-1, "negative is unbounded in SQLite", id="negative"),
    pytest.param(0, "a page of nothing is a bug, not a query", id="zero"),
    pytest.param(501, "above the cap", id="over-cap"),
])
def test_list_rejects_a_limit_outside_the_allowed_range(client, services,
                                                        tmp_path, limit, why):
    _add(services, tmp_path, name="a")
    response = client.get(f"/api/runs?limit={limit}")
    assert response.status_code == 422, why
    # Refused outright: no rows may come back with the error.
    assert "detail" in response.json()


def test_list_accepts_the_edges_of_the_allowed_range(client, services,
                                                     tmp_path):
    _add(services, tmp_path, name="a")
    assert client.get("/api/runs?limit=1").status_code == 200
    assert client.get("/api/runs?limit=500").status_code == 200


def test_list_filters_by_label(client, services, tmp_path):
    _add(services, tmp_path, name="a")
    _add(services, tmp_path, name="b", label="other")
    assert len(client.get("/api/runs?label=other").json()) == 1
    assert len(client.get("/api/runs?label=missing").json()) == 0


def test_csv_is_streamed(client, services, tmp_path):
    run_id = _add(services, tmp_path)
    response = client.get(f"/api/runs/{run_id}/csv")
    assert response.status_code == 200
    assert "frame,time_ms" in response.text


def test_csv_404_when_the_folder_has_none(client, services, tmp_path):
    folder = tmp_path / "measure" / "empty"
    folder.mkdir(parents=True)
    run_id = services.store.add_run(RunRecord(
        kind="piston", captured_at="x", measure_dir=str(folder)))
    assert client.get(f"/api/runs/{run_id}/csv").status_code == 404


def test_csv_404_for_unknown_run(client):
    assert client.get("/api/runs/999/csv").status_code == 404


def test_media_serves_a_file_from_the_run_folder(client, services, tmp_path):
    run_id = _add(services, tmp_path)
    response = client.get(
        f"/api/runs/{run_id}/media/piston_run_speed_time.png")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


def test_media_404_for_unknown_run(client):
    assert client.get("/api/runs/999/media/x.png").status_code == 404


def test_media_404_for_a_name_that_is_not_there(client, services, tmp_path):
    run_id = _add(services, tmp_path)
    assert client.get(f"/api/runs/{run_id}/media/nope.png").status_code == 404


def test_media_refuses_a_path_outside_the_run_folder(client, services, tmp_path):
    """A run id plus a crafted name must not read arbitrary files.

    This POSIX spelling never reaches the handler: starlette unquotes the path
    before routing, so ``%2F`` becomes a separator and ``{name}`` (one segment)
    no longer matches. The router answers it. The Windows spelling below is the
    one that reaches the guard, which is why both are here.
    """
    run_id = _add(services, tmp_path)
    response = client.get(f"/api/runs/{run_id}/media/..%2F..%2Frig.db")
    assert response.status_code in (400, 404)


# --- traversal, spelled every way this rig can be attacked -----------------
# The database and settings/calibration.json live under the data root, one
# and two levels above a measure folder, so an escape here is not academic.

def test_media_refuses_a_windows_traversal(client, services, tmp_path):
    r"""``..\..\rig.db`` is ONE url segment, so unlike ``..%2F`` it really does
    reach the handler -- and it names the rig's own database."""
    run_id = _add(services, tmp_path)
    assert (tmp_path / "rig.db").is_file()          # the target really exists
    response = client.get(f"/api/runs/{run_id}/media/..%5C..%5Crig.db")
    assert response.status_code == 404
    # The guard answered, not the router: this really did reach the handler.
    assert response.json()["detail"] == "no such file"
    assert b"SQLite" not in response.content


def test_media_refuses_a_bare_parent(client, services, tmp_path):
    """Percent-encoded, because httpx collapses a literal ``..`` segment away
    before it is ever sent -- an attacker's client would not."""
    run_id = _add(services, tmp_path)
    response = client.get(f"/api/runs/{run_id}/media/%2E%2E")
    assert response.status_code == 404
    assert response.json()["detail"] == "no such file"


@pytest.mark.parametrize("name, why", [
    pytest.param("{db}", "absolute", id="absolute"),
    # Not absolute: Path joins "C:rig.db" as a drive-relative name, which
    # resolves against the process cwd rather than the run folder.
    pytest.param("C:rig.db", "drive-relative", id="drive-relative"),
    pytest.param(r"\\server\share\secret.png", "UNC", id="unc"),
])
def test_media_refuses_a_rooted_name(client, services, tmp_path, name, why):
    run_id = _add(services, tmp_path)
    name = quote(name.format(db=str(tmp_path / "rig.db")), safe="")
    response = client.get(f"/api/runs/{run_id}/media/{name}")
    assert response.status_code == 400, why
    assert response.json()["detail"] == "media name must be relative"


def test_media_serves_a_name_whose_case_differs(client, services, tmp_path):
    """Windows paths are case-insensitive, so the containment check must be
    too -- refusing this would be a bug, not caution."""
    run_id = _add(services, tmp_path)
    response = client.get(
        f"/api/runs/{run_id}/media/PISTON_RUN_SPEED_TIME.PNG")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


@pytest.mark.skipif(sys.platform != "win32", reason="mklink is Windows-only")
def test_media_refuses_a_junction_out_of_the_run_folder(client, services,
                                                        tmp_path):
    """A directory junction needs no privilege, so unlike the symlink case
    this link traversal really executes here. ``resolve`` sees through the
    junction; a check on the string handed in would not."""
    run_id = _add(services, tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "rig.db").write_bytes(b"SQLite format 3\x00")
    link = tmp_path / "measure" / "piston_run" / "link"
    if subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(vault)],
                      capture_output=True).returncode != 0:
        pytest.skip("junctions not permitted on this machine")
    try:
        response = client.get(f"/api/runs/{run_id}/media/link%5Crig.db")
        assert response.status_code == 404
        assert response.json()["detail"] == "no such file"
        assert b"SQLite" not in response.content
    finally:
        link.rmdir()          # removes the junction, not the directory below


def test_media_refuses_a_symlink_out_of_the_run_folder(client, services,
                                                       tmp_path):
    """The name is innocent; the file it resolves to is not. This is why the
    check compares RESOLVED paths and not the string it was handed."""
    run_id = _add(services, tmp_path)
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"\x89PNGSECRET")
    link = tmp_path / "measure" / "piston_run" / "innocent.png"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):           # Windows needs privilege
        pytest.skip("symlinks not permitted on this machine")
    response = client.get(f"/api/runs/{run_id}/media/innocent.png")
    assert response.status_code in (400, 404)
    assert b"SECRET" not in response.content


def test_import_scans_the_measure_root(client, services, tmp_path):
    name = "piston_2026-08-14-10-00-00_320x120_X"
    folder = services.paths.measures / name
    folder.mkdir(parents=True)
    (folder / f"{name}_speed.csv").write_text(
        "frame,time_ms\n\nstroke_mm,1.0\n", encoding="utf-8")
    body = client.post("/api/runs/import").json()
    assert body["imported"] == 1


def test_import_reports_what_it_skipped(client, services, tmp_path):
    (services.paths.measures / "not-a-run").mkdir(parents=True)
    body = client.post("/api/runs/import").json()
    assert body["imported"] == 0
    assert body["skipped"][0][0] == "not-a-run"


def test_summary_over_selected_runs(client, services, tmp_path):
    ids = [_add(services, tmp_path, name=f"r{i}") for i in range(2)]
    response = client.post("/api/summary", json={"run_ids": ids})
    assert response.status_code in (200, 422)   # 422 if folders lack metrics


def test_summary_aggregates_measured_runs(client, services, tmp_path):
    ids = [_measured(services, tmp_path, "m0", 1.0, 100.0),
           _measured(services, tmp_path, "m1", 3.0, 140.0)]
    body = client.post("/api/summary", json={"run_ids": ids}).json()
    assert body["stats"]["stroke_mm"]["n"] == 2
    assert body["stats"]["stroke_mm"]["mean"] == pytest.approx(2.0)
    # A metric no run recorded has no statistics -- null, never a NaN, which
    # JSON cannot carry and which starlette refuses to encode.
    assert body["stats"]["peak_jet_speed_m_s"]["n"] == 0
    assert body["stats"]["peak_jet_speed_m_s"]["mean"] is None
    assert Path(body["path"]).is_file()


def test_summary_names_the_folders_it_skipped(client, services, tmp_path):
    good = _measured(services, tmp_path, "m0", 1.0, 100.0)
    bad = _add(services, tmp_path, name="nometrics")
    body = client.post("/api/summary", json={"run_ids": [good, bad]}).json()
    assert body["skipped"][0][0] == "nometrics"


def test_summary_422_when_no_folder_holds_a_measured_run(client, services,
                                                         tmp_path):
    """Not a server fault: the operator picked folders that carry no numbers,
    and has to be told which."""
    run_id = _add(services, tmp_path, name="nometrics")
    response = client.post("/api/summary", json={"run_ids": [run_id]})
    assert response.status_code == 422
    assert "speed.csv" in response.json()["detail"]


def test_summary_404_for_an_unknown_run(client):
    assert client.post("/api/summary",
                       json={"run_ids": [999]}).status_code == 404
