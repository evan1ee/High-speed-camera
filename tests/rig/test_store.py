# tests/rig/test_store.py
"""SQLite holds one row per measured run; per-frame data stays in the CSV."""
import pytest

from hsc.rig.store import RunRecord, RunStore


def _record(**over):
    base = dict(
        label="IN37-30U", kind="piston", captured_at="2026-08-14T14:28:09",
        source_dir=r"data\captures\piston_x", injection_dir=r"data\injection images\piston_x",
        measure_dir=r"data\measure\piston_x", roi="320x120", fps=1738.77,
        exposure_us=500.0, timebase="timestamps (ns)", mm_per_px=0.059385,
        scale_source="calibration.json", barrel_mm=6.12, orifice_mm=0.155,
        density=1000.0, stroke_px=172.6, stroke_mm=10.254, duration_ms=112.1,
        mean_speed_mm_s=91.5, peak_speed_mm_s=194.0,
        peak_jet_speed_m_s=302.4, peak_jet_pressure_MPa=45.7,
        unstable_frames=1, measured_count=268)
    base.update(over)
    return RunRecord(**base)


def test_add_and_get_round_trip(tmp_path):
    store = RunStore(tmp_path / "rig.db")
    run_id = store.add_run(_record())
    got = store.get_run(run_id)
    assert got.label == "IN37-30U"
    assert got.stroke_mm == pytest.approx(10.254)
    assert got.id == run_id


def test_get_returns_none_for_an_unknown_id(tmp_path):
    assert RunStore(tmp_path / "rig.db").get_run(999) is None


def test_list_is_newest_first_and_filterable(tmp_path):
    store = RunStore(tmp_path / "rig.db")
    store.add_run(_record(captured_at="2026-08-14T10:00:00", label="A",
                          measure_dir=r"data\measure\a"))
    store.add_run(_record(captured_at="2026-08-14T14:00:00", label="B",
                          measure_dir=r"data\measure\b"))
    store.add_run(_record(captured_at="2026-08-14T12:00:00", label="C",
                          kind="spray", measure_dir=r"data\measure\c"))
    assert [r.label for r in store.list_runs()] == ["B", "C", "A"]
    assert [r.label for r in store.list_runs(kind="piston")] == ["B", "A"]
    assert [r.label for r in store.list_runs(label="A")] == ["A"]
    assert len(store.list_runs(limit=1)) == 1


def test_measure_dir_is_unique_so_import_is_idempotent(tmp_path):
    """The importer re-scans folders on every start; a run must not double."""
    store = RunStore(tmp_path / "rig.db")
    store.add_run(_record(measure_dir=r"data\measure\same"))
    store.add_run(_record(measure_dir=r"data\measure\same", stroke_mm=99.0))
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].stroke_mm == pytest.approx(99.0)   # upsert, latest wins


def test_a_writer_that_knows_less_does_not_erase_what_is_stored(tmp_path):
    """The importer can only read a measure FOLDER, so it leaves every
    capture-side column None -- and it re-scans at every start. A blind
    ``SET col = excluded.col`` therefore wiped them on the first restart after
    each run: unconditional, silent loss of the only record of where the run
    came from."""
    store = RunStore(tmp_path / "rig.db")
    run_id = store.add_run(_record())
    store.add_run(RunRecord(                      # what the importer can build
        kind="piston", captured_at="2026-08-14T14:28:09",
        measure_dir=r"data\measure\piston_x", label="IN37-30U",
        stroke_mm=10.254))
    got = store.get_run(run_id)
    assert got.source_dir == r"data\captures\piston_x"
    assert got.injection_dir == r"data\injection images\piston_x"
    assert got.exposure_us == 500.0
    assert got.measured_count == 268


def test_a_later_writer_still_overwrites_the_values_it_does_know(tmp_path):
    """The merge protects unknown columns only. A re-measurement that produces
    a new number must still replace the old one, or the row would freeze at
    whatever was written first."""
    store = RunStore(tmp_path / "rig.db")
    run_id = store.add_run(_record())
    store.add_run(_record(stroke_mm=11.0, peak_speed_mm_s=None))
    got = store.get_run(run_id)
    assert got.stroke_mm == pytest.approx(11.0)     # known: replaced
    assert got.peak_speed_mm_s == pytest.approx(194.0)   # unknown: kept


def test_optional_metrics_may_be_missing(tmp_path):
    """Runs measured before the jet columns existed still import."""
    store = RunStore(tmp_path / "rig.db")
    run_id = store.add_run(_record(peak_jet_speed_m_s=None,
                                   peak_jet_pressure_MPa=None))
    got = store.get_run(run_id)
    assert got.peak_jet_speed_m_s is None


def test_settings_round_trip(tmp_path):
    store = RunStore(tmp_path / "rig.db")
    store.set_setting("roi", "320x120")
    store.set_setting("exposure_us", "500")
    store.set_setting("roi", "320x240")
    assert store.get_settings() == {"roi": "320x240", "exposure_us": "500"}


def test_schema_survives_reopening(tmp_path):
    path = tmp_path / "rig.db"
    RunStore(path).add_run(_record())
    assert len(RunStore(path).list_runs()) == 1


def test_run_by_measure_dir_round_trip_and_miss(tmp_path):
    store = RunStore(tmp_path / "rig.db")
    store.add_run(_record(measure_dir=r"data\measure\piston_x"))
    got = store.run_by_measure_dir(r"data\measure\piston_x")
    assert got.label == "IN37-30U"
    assert store.run_by_measure_dir(r"data\measure\unknown") is None
