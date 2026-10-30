"""Batch statistics across measured piston runs."""

import csv

import numpy as np
import pytest

from hsc import summary


def make_run(tmp_path, name, stroke, peak, duration, jet=None, pressure=None):
    """A folder shaped like a measured run: per-frame rows then the summary."""
    folder = tmp_path / name
    folder.mkdir()
    lines = [
        "frame,time_ms,x_px,distance_px,distance_mm,speed_mm_s,speed_m_s,"
        "jet_speed_m_s,jet_pressure_MPa,k,n_points,rms_px,coverage,"
        "at_border,stable",
        "frame_000001.bmp,0.000,40.0,0.0,0.0,1.0,0.001,1.5,0.001,"
        "0.01,18,0.1,1.000,no,yes",
        "",
        f"stroke_mm,{stroke}",
        f"peak_speed_mm_s,{peak}",
        f"duration_ms,{duration}",
    ]
    if jet is not None:
        lines.append(f"peak_jet_speed_m_s,{jet}")
    if pressure is not None:
        lines.append(f"peak_jet_pressure_MPa,{pressure}")
    lines.append("timebase,timestamps (ns)")
    (folder / f"{name}_speed.csv").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
    return folder


def test_read_run_takes_the_summary_not_the_frame_rows(tmp_path):
    folder = make_run(tmp_path, "run_a", 9.0, 130.0, 100.0, 200.0, 20.0)
    values = summary.read_run(folder)
    assert values == {
        "stroke_mm": 9.0, "peak_speed_mm_s": 130.0, "duration_ms": 100.0,
        "peak_jet_speed_m_s": 200.0, "peak_jet_pressure_MPa": 20.0,
    }


def test_statistics_across_runs(tmp_path):
    for i, stroke in enumerate((9.0, 10.0, 11.0)):
        make_run(tmp_path, f"run_{i}", stroke, 130.0 + i, 100.0, 200.0, 20.0)
    folders = sorted(p for p in tmp_path.iterdir() if p.is_dir())
    runs, skipped = summary.collect(folders)
    assert len(runs) == 3 and not skipped

    stats = summary.describe(runs)["stroke_mm"]
    assert stats["n"] == 3
    assert stats["mean"] == pytest.approx(10.0)
    assert stats["std"] == pytest.approx(np.std([9, 10, 11], ddof=1))
    assert stats["min"] == 9.0 and stats["max"] == 11.0
    assert stats["median"] == pytest.approx(10.0)
    assert stats["cv_percent"] == pytest.approx(100 * stats["std"] / 10.0)


def test_runs_without_jet_columns_still_contribute(tmp_path):
    """Runs measured before the jet columns existed keep their stroke and
    speed in the batch instead of dropping out of it."""
    make_run(tmp_path, "old_run", 9.0, 130.0, 100.0)              # no jet
    make_run(tmp_path, "new_run", 11.0, 140.0, 100.0, 200.0, 20.0)
    folders = sorted(p for p in tmp_path.iterdir() if p.is_dir())
    runs, _skipped = summary.collect(folders)
    stats = summary.describe(runs)
    assert stats["stroke_mm"]["n"] == 2
    assert stats["peak_jet_speed_m_s"]["n"] == 1


def test_folders_without_a_run_are_reported_not_averaged(tmp_path):
    """Quietly averaging fewer runs than the operator selected would be the
    worst outcome; the skipped ones are named, in the log and in the CSV."""
    make_run(tmp_path, "good", 9.0, 130.0, 100.0, 200.0, 20.0)
    (tmp_path / "empty").mkdir()
    folders = sorted(p for p in tmp_path.iterdir() if p.is_dir())
    result = summary.summarize(folders, tmp_path / "out")
    assert len(result["runs"]) == 1
    assert [name for name, _r in result["skipped"]] == ["empty"]
    assert "empty" in (tmp_path / "out").joinpath(
        result["path"].split("\\")[-1]).read_text(encoding="utf-8")


def test_summary_csv_has_a_row_per_run_and_a_statistics_block(tmp_path):
    for i in range(3):
        make_run(tmp_path, f"run_{i}", 9.0 + i, 130.0, 100.0, 200.0, 20.0)
    folders = sorted(p for p in tmp_path.iterdir() if p.is_dir())
    result = summary.summarize(folders, tmp_path / "out")

    from pathlib import Path

    text = Path(result["path"]).read_text(encoding="utf-8")
    assert Path(result["path"]).parent == tmp_path / "out"
    assert Path(result["path"]).name.startswith(summary.FILE_PREFIX)

    blocks = [b for b in text.split("\n\n") if b.strip()]
    per_run = list(csv.DictReader(blocks[0].splitlines()))
    assert [r["run"] for r in per_run] == ["run_0", "run_1", "run_2"]
    assert float(per_run[2]["stroke_mm"]) == pytest.approx(11.0)

    stats_rows = {r["statistic"]: r
                  for r in csv.DictReader(blocks[1].splitlines())}
    assert set(stats_rows) == set(summary.STATISTICS)
    assert float(stats_rows["mean"]["stroke_mm"]) == pytest.approx(10.0)
    assert int(stats_rows["n"]["stroke_mm"]) == 3


def test_no_measurable_run_raises(tmp_path):
    (tmp_path / "nothing").mkdir()
    with pytest.raises(RuntimeError, match="measured piston run"):
        summary.summarize([tmp_path / "nothing"], tmp_path / "out")
