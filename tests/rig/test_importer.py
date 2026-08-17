# tests/rig/test_importer.py
"""Existing run folders import without translation: hsc.summary already parses
exactly the summary block the store keeps."""
from hsc.rig.importer import import_measure_root
from hsc.rig.store import RunRecord, RunStore

CSV = """frame,time_ms,x_px,distance_px,distance_mm,speed_mm_s,speed_m_s,k,n_points,rms_px,coverage,at_border,stable
frame_000001.bmp,0.000,117.0,0.000,0.0000,0.00,0.0000,-0.02,50,0.30,1.000,no,yes
frame_000002.bmp,0.575,117.6,0.600,0.0356,62.00,0.0620,-0.02,50,0.30,1.000,no,yes

unstable_frames,1
stroke_px,172.600
stroke_mm,10.2540
duration_ms,112.1000
mean_speed_mm_s,91.5000
peak_speed_mm_s,194.0000
peak_jet_speed_m_s,302.4000
peak_jet_pressure_MPa,45.7000
barrel_mm,6.1200
orifice_mm,0.1550
area_ratio,1558.9761
fluid_density,1000.0000
mm_per_px,0.0594
scale_source,calibration.json
fps,1738.7676
timebase,timestamps (ns)
reference_frame,frame_000001.bmp
"""


def _run_folder(root, name, csv=CSV):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / f"{name}_speed.csv").write_text(csv, encoding="utf-8")
    return folder


def test_imports_a_measured_run(tmp_path):
    root = tmp_path / "measure"
    _run_folder(root, "piston_2026-08-14-14-28-09_320x120_IN37-30U")
    store = RunStore(tmp_path / "rig.db")

    result = import_measure_root(root, store)

    assert result.imported == 1
    run = store.list_runs()[0]
    assert run.kind == "piston"
    assert run.label == "IN37-30U"
    assert run.roi == "320x120"
    assert run.stroke_mm == 10.254
    assert run.peak_jet_pressure_MPa == 45.7
    assert run.fps == 1738.7676
    assert run.timebase == "timestamps (ns)"
    # Fields hsc.summary.read_run does not surface (outside its KEYS tuple) --
    # must come from the CSV's raw summary lines, not silently stay None.
    assert run.mm_per_px == 0.0594
    assert run.scale_source == "calibration.json"
    assert run.barrel_mm == 6.12
    assert run.orifice_mm == 0.155
    assert run.density == 1000.0
    assert run.stroke_px == 172.6
    assert run.mean_speed_mm_s == 91.5
    assert run.unstable_frames == 1


def test_is_idempotent(tmp_path):
    root = tmp_path / "measure"
    _run_folder(root, "piston_2026-08-14-14-28-09_320x120_IN37-30U")
    store = RunStore(tmp_path / "rig.db")
    import_measure_root(root, store)
    second = import_measure_root(root, store)
    assert second.imported == 1
    assert len(store.list_runs()) == 1


def test_the_startup_rescan_keeps_what_only_the_pipeline_knew(tmp_path):
    """import_measure_root runs from __main__.build at EVERY start, and a
    measure folder cannot tell it which burst the run came from, what exposure
    was used, how many frames were measured, or whether the burst was
    truncated. Re-importing must therefore leave those columns alone -- they
    were lost on the first restart after every run."""
    root = tmp_path / "measure"
    folder = _run_folder(root, "piston_2026-08-14-14-28-09_320x120_IN37-30U")
    store = RunStore(tmp_path / "rig.db")
    run_id = store.add_run(RunRecord(
        kind="piston", captured_at="2026-08-14T14:28:09",
        measure_dir=str(folder), label="IN37-30U",
        source_dir=r"data\captures\piston_x",
        injection_dir=r"data\injection images\piston_x",
        exposure_us=500.0, measured_count=268, truncated=1, dropped=2))

    assert import_measure_root(root, store).imported == 1

    run = store.get_run(run_id)
    assert run.source_dir == r"data\captures\piston_x"
    assert run.injection_dir == r"data\injection images\piston_x"
    assert run.exposure_us == 500.0
    assert run.measured_count == 268
    assert (run.truncated, run.dropped) == (1, 2)   # the burst's own warnings
    assert run.stroke_mm == 10.254        # and the folder's own numbers land
    assert len(store.list_runs()) == 1     # still one row, not a duplicate


def test_folder_without_a_csv_is_skipped_with_a_reason(tmp_path):
    root = tmp_path / "measure"
    (root / "not_a_run").mkdir(parents=True)
    result = import_measure_root(root, RunStore(tmp_path / "rig.db"))
    assert result.imported == 0
    assert result.skipped == [("not_a_run", "no piston speed CSV")]


def test_run_measured_before_the_jet_columns_still_imports(tmp_path):
    root = tmp_path / "measure"
    older = "\n".join(line for line in CSV.splitlines()
                      if not line.startswith("peak_jet"))
    _run_folder(root, "piston_2026-08-01-10-00-00_320x240", csv=older)
    store = RunStore(tmp_path / "rig.db")
    assert import_measure_root(root, store).imported == 1
    run = store.list_runs()[0]
    assert run.stroke_mm == 10.254
    assert run.peak_jet_speed_m_s is None


def test_missing_measure_root_is_not_an_error(tmp_path):
    result = import_measure_root(tmp_path / "absent", RunStore(tmp_path / "d.db"))
    assert result.imported == 0 and result.skipped == []


def test_label_and_roi_are_parsed_from_the_folder_name(tmp_path):
    root = tmp_path / "measure"
    _run_folder(root, "piston_2026-08-14-10-27-10_320x120_IN38-4U")
    store = RunStore(tmp_path / "rig.db")
    import_measure_root(root, store)
    run = store.list_runs()[0]
    assert run.label == "IN38-4U"
    assert run.captured_at == "2026-08-14T10:27:10"


def test_folder_name_without_a_date_stamp_falls_back_to_defaults(tmp_path):
    """A run folder can't be dated/labelled by name alone -- don't guess."""
    root = tmp_path / "measure"
    _run_folder(root, "renamed_by_hand")
    store = RunStore(tmp_path / "rig.db")
    result = import_measure_root(root, store)
    assert result.imported == 1
    run = store.list_runs()[0]
    assert run.kind == "piston"
    assert run.captured_at == ""
    assert run.roi is None
    assert run.label is None


def test_non_numeric_summary_value_becomes_none(tmp_path):
    """measure_piston writes "n/a" for an unmeasurable figure -- don't crash,
    don't invent a number."""
    root = tmp_path / "measure"
    bad = "\n".join(
        "mm_per_px,n/a" if line.startswith("mm_per_px") else line
        for line in CSV.splitlines())
    _run_folder(root, "piston_2026-08-14-14-28-09_320x120_IN37-30U", csv=bad)
    store = RunStore(tmp_path / "rig.db")
    import_measure_root(root, store)
    run = store.list_runs()[0]
    assert run.mm_per_px is None
    assert run.stroke_mm == 10.254   # unaffected fields still import


def test_missing_raw_numeric_fields_stay_none(tmp_path):
    """A field absent from the CSV's summary block stays None -- never guessed."""
    root = tmp_path / "measure"
    trimmed = "\n".join(
        line for line in CSV.splitlines()
        if not line.startswith(("fps", "unstable_frames", "barrel_mm")))
    _run_folder(root, "piston_2026-08-14-14-28-09_320x120_IN37-30U", csv=trimmed)
    store = RunStore(tmp_path / "rig.db")
    import_measure_root(root, store)
    run = store.list_runs()[0]
    assert run.fps is None
    assert run.unstable_frames is None
    assert run.barrel_mm is None
    assert run.mm_per_px == 0.0594   # unaffected fields still import


def test_unreadable_folder_is_skipped_without_stopping_the_scan(tmp_path):
    """import_measure_root runs at every startup over ~90-180 folders; one
    bad folder (locked, permission error, removed mid-scan) must not abort
    the loop and discard the imported/skipped progress already collected.

    Simulated here without mocking: a directory named "*_speed.csv" instead
    of a file still matches summary.find_csv's glob, but reading it as text
    raises PermissionError (an OSError) on Windows, IsADirectoryError
    (also an OSError) on POSIX -- either way a real filesystem failure."""
    root = tmp_path / "measure"
    bad = root / "piston_2026-08-14-00-00-00_320x120_BAD"
    bad.mkdir(parents=True)
    (bad / f"{bad.name}_speed.csv").mkdir()
    good = _run_folder(root, "piston_2026-08-14-14-28-09_320x120_IN37-30U")
    store = RunStore(tmp_path / "rig.db")

    result = import_measure_root(root, store)

    assert result.imported == 1
    assert len(result.skipped) == 1
    name, reason = result.skipped[0]
    assert name == bad.name
    assert reason   # a real message, mirroring summary.collect's str(exc)
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].measure_dir == str(good)


def test_loose_files_in_measure_root_are_ignored(tmp_path):
    """hsc.summary.write_summary drops summary_<stamp>.csv directly into the
    measure root, beside the run folders -- iterdir() sees it too."""
    root = tmp_path / "measure"
    root.mkdir(parents=True)
    (root / "summary_2026-01-01-00-00-00.csv").write_text(
        "run,stroke_mm\n", encoding="utf-8")
    _run_folder(root, "piston_2026-08-14-14-28-09_320x120_IN37-30U")
    store = RunStore(tmp_path / "rig.db")
    result = import_measure_root(root, store)
    assert result.imported == 1
    assert result.skipped == []
