"""Piston distance/speed measurement: CSV, curves, and the time base.

Builds a real folder of BMP frames with an exactly known stroke, so the
reported mm and mm/s can be checked against ground truth end to end. Frames
are written with cv2 (bottom-up BMPs), which also exercises the row-order
flip that bit the monitor folders once before.
"""

import csv
import json

import cv2
import numpy as np
import pytest

from hsc import measure_piston as mp
from test_piston_track import make_frame


MM_PER_PX = 0.05
FPS = 1000.0
PRE, MOVE, POST = 30, 100, 30
STEP_PX = 1.2

# Ground truth of the synthetic run below.
STROKE_MM = MOVE * STEP_PX * MM_PER_PX          # 6.0 mm
DURATION_MS = MOVE * 1000.0 / FPS               # 100 ms
SPEED_MM_S = STEP_PX * MM_PER_PX * FPS          # 60 mm/s


def _positions():
    x0 = 40.0
    pos = [x0] * PRE
    pos += [x0 + STEP_PX * (i + 1) for i in range(MOVE)]
    return pos + [pos[-1]] * POST


def make_folder(tmp_path, meta=True, times_us=None, name="piston_run"):
    folder = tmp_path / name
    folder.mkdir()
    positions = _positions()
    for i, x in enumerate(positions):
        frame = make_frame(edge_x=x, noise=1.0, seed=i)
        cv2.imwrite(str(folder / f"frame_{i + 1:06d}.bmp"), frame)
    if meta:
        payload = {
            "pre_frames": PRE,
            "onset_index": PRE,
            "copy_start": 0,
            "copy_end": len(positions) - 1,
            "method": "test",
            "fps": FPS,
            "frame_times_us": times_us,
        }
        (folder / "piston_meta.json").write_text(json.dumps(payload),
                                                 encoding="utf-8")
    return folder


def _rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------- time base ----
def test_timebase_uses_fps_when_no_timestamps():
    times, source, fps = mp.resolve_timebase({"fps": 500.0}, n=10, fps=None)
    assert source == "fps"
    assert fps == 500.0
    assert times[1] - times[0] == pytest.approx(1 / 500.0)


def test_timebase_prefers_frame_timestamps():
    stamps = [i * 1000 for i in range(10)]        # 1 ms in microseconds
    times, source, fps = mp.resolve_timebase(
        {"fps": 1000.0, "frame_times_us": stamps}, n=10, fps=None)
    assert source.startswith("timestamps")
    assert fps == pytest.approx(1000.0, rel=1e-6)
    assert times[-1] == pytest.approx(0.009)


@pytest.mark.parametrize("unit,scale", [("ns", 1000.0), ("ms", 0.001)])
def test_timebase_detects_the_timestamp_unit(unit, scale):
    """The SDK's timeStamp tick unit is undocumented; it is inferred by
    agreeing with the burst's measured FPS instead of being assumed."""
    stamps = [int(i * 1000 * scale) for i in range(20)]
    times, source, fps = mp.resolve_timebase(
        {"fps": 1000.0, "frame_times_us": stamps}, n=20, fps=None)
    assert unit in source
    assert fps == pytest.approx(1000.0, rel=1e-3)


def test_timebase_rejects_nonsense_timestamps():
    """Timestamps that disagree with the measured FPS by orders of magnitude
    (frozen clock, wrong field) must not silently produce a wrong speed."""
    stamps = [0] * 20
    _times, source, fps = mp.resolve_timebase(
        {"fps": 1000.0, "frame_times_us": stamps}, n=20, fps=None)
    assert source == "fps"
    assert fps == 1000.0


def test_timebase_without_any_timing_is_an_error():
    with pytest.raises(RuntimeError, match="frame rate"):
        mp.resolve_timebase({}, n=10, fps=None)


# ------------------------------------------------------------- measuring ----
def test_measure_folder_reports_the_true_stroke(tmp_path):
    src = make_folder(tmp_path)
    result = mp.measure_folder(src, dest_base=tmp_path / "measure",
                               mm_per_px=MM_PER_PX)

    assert result["stroke_mm"] == pytest.approx(STROKE_MM, rel=0.02)
    assert result["duration_ms"] == pytest.approx(DURATION_MS, abs=6.0)
    assert result["peak_speed_mm_s"] == pytest.approx(SPEED_MM_S, rel=0.06)
    assert result["mean_speed_mm_s"] == pytest.approx(SPEED_MM_S, rel=0.10)
    assert result["mm_per_px"] == MM_PER_PX


def test_measure_folder_writes_images_csv_and_curves(tmp_path):
    src = make_folder(tmp_path)
    result = mp.measure_folder(src, dest_base=tmp_path / "measure",
                               mm_per_px=MM_PER_PX)
    dest = tmp_path / "measure" / src.name

    # Reports are named after their folder, so they identify their own run.
    assert mp.output_path(dest, mp.CSV_SUFFIX).exists()
    assert mp.output_path(dest, mp.DISTANCE_PLOT_SUFFIX).exists()
    assert mp.output_path(dest, mp.SPEED_PLOT_SUFFIX).exists()
    assert mp.output_path(dest, mp.CSV_SUFFIX).name.startswith(dest.name)
    images = sorted(dest.glob("frame_*.bmp"))
    assert len(images) == PRE + MOVE + POST == result["measured_count"]
    # Annotated output keeps the capture size and gains the green line.
    annotated = cv2.imread(str(images[PRE + 50]), cv2.IMREAD_COLOR)
    assert annotated.shape[:2] == (240, 320)
    green = (annotated[:, :, 1].astype(int)
             - annotated[:, :, 2].astype(int)) > 60
    assert green.sum() > 20


def test_csv_distance_matches_ground_truth(tmp_path):
    src = make_folder(tmp_path)
    mp.measure_folder(src, dest_base=tmp_path / "measure", mm_per_px=MM_PER_PX)
    rows = _rows(mp.output_path(tmp_path / "measure" / src.name, mp.CSV_SUFFIX))

    frame_rows = [r for r in rows if r["frame"].startswith("frame_")]
    assert len(frame_rows) == PRE + MOVE + POST
    # Zero is the RESTING position, so every frame before the stroke reads 0 --
    # not the stroke-start frame, which has already travelled one step.
    for row in frame_rows[:PRE]:
        assert float(row["distance_mm"]) == pytest.approx(0.0, abs=0.02)
    # The stroke's first frame has moved exactly one step from rest.
    assert float(frame_rows[PRE]["distance_mm"]) == pytest.approx(
        STEP_PX * MM_PER_PX, abs=0.02)
    # 50 frames further in: 51 * 1.2 px * 0.05 mm/px.
    assert float(frame_rows[PRE + 50]["distance_mm"]) == pytest.approx(
        51 * STEP_PX * MM_PER_PX, abs=0.05)
    assert float(frame_rows[PRE + 50]["time_ms"]) == pytest.approx(50.0, abs=0.5)


def test_measure_folder_falls_back_to_the_fps_argument(tmp_path):
    """A folder copied by hand (no meta) still measures, using the FPS the
    operator supplies."""
    src = make_folder(tmp_path, meta=False)
    result = mp.measure_folder(src, dest_base=tmp_path / "measure",
                               fps=FPS, mm_per_px=MM_PER_PX)
    assert result["timebase"] == "fps"
    assert result["peak_speed_mm_s"] == pytest.approx(SPEED_MM_S, rel=0.06)


def test_measure_folder_without_calibration_still_reports_pixels(tmp_path):
    src = make_folder(tmp_path)
    result = mp.measure_folder(src, dest_base=tmp_path / "measure",
                               mm_per_px=0.0)
    assert result["mm_per_px"] == 0.0
    assert result["stroke_px"] == pytest.approx(MOVE * STEP_PX, rel=0.02)
    assert np.isnan(result["stroke_mm"])


def test_speed_plot_marks_the_reported_peak(tmp_path):
    """The peak in the summary must be visible on the curve it came from --
    the two disagreeing once already cost a round of confusion."""
    src = make_folder(tmp_path)
    result = mp.measure_folder(src, dest_base=tmp_path / "measure",
                               mm_per_px=MM_PER_PX)
    plot = cv2.imread(
        str(mp.output_path(tmp_path / "measure" / src.name,
                           mp.SPEED_PLOT_SUFFIX)), cv2.IMREAD_COLOR)
    from hsc import piston_plot

    red = np.all(np.abs(plot.astype(int) - np.array(piston_plot.MARK)) < 60,
                 axis=2)
    assert red.any(), "no peak marker drawn"
    # It must be a horizontal guide across the plot, not just the label text.
    # (Checked by extent, not by a full row: the line is anti-aliased, so most
    # of its pixels are blended away from the pure marker colour.)
    columns = np.flatnonzero(red.any(axis=0))
    assert columns.max() - columns.min() > plot.shape[1] // 2


def test_jet_speed_and_pressure_from_piston_speed():
    """Volume conservation through the orifice, against the worked example:
    a 6.12 mm barrel, a 0.155 mm orifice and a 131 mm/s piston.

        v_jet = v_piston * (D_barrel / D_orifice)^2
        p     = rho/2 * v_jet^2
    """
    jet, mpa, ratio = mp.jet_from_piston(131.0, barrel_mm=6.12,
                                         orifice_mm=0.155, density=1000.0)
    assert ratio == pytest.approx((6.12 / 0.155) ** 2, rel=1e-9)
    assert float(jet) == pytest.approx(204.23, abs=0.05)
    assert float(mpa) == pytest.approx(0.5 * 1000 * 204.23 ** 2 / 1e6, abs=0.02)
    # Scales with the square of the diameter ratio, linearly with speed.
    doubled, _p, _r = mp.jet_from_piston(262.0, 6.12, 0.155, 1000.0)
    assert float(doubled) == pytest.approx(2 * float(jet), rel=1e-9)


def test_jet_columns_and_curves_are_written(tmp_path):
    src = make_folder(tmp_path)
    result = mp.measure_folder(src, dest_base=tmp_path / "measure",
                               mm_per_px=MM_PER_PX, barrel_mm=6.12,
                               orifice_mm=0.155)
    dest = tmp_path / "measure" / src.name
    assert mp.output_path(dest, mp.JET_SPEED_PLOT_SUFFIX).exists()
    assert mp.output_path(dest, mp.JET_PRESSURE_PLOT_SUFFIX).exists()

    rows = _rows(mp.output_path(dest, mp.CSV_SUFFIX))
    moving = [r for r in rows if r["frame"].startswith("frame_")
              and r["jet_speed_m_s"] not in ("", None)]
    assert moving, "no jet speed written"
    # The jet column is the piston column scaled by the area ratio.
    ratio = (6.12 / 0.155) ** 2
    row = moving[len(moving) // 2]
    assert float(row["jet_speed_m_s"]) == pytest.approx(
        float(row["speed_mm_s"]) * ratio / 1000.0, rel=1e-3)
    assert float(row["jet_pressure_MPa"]) == pytest.approx(
        0.5 * 1000 * float(row["jet_speed_m_s"]) ** 2 / 1e6, rel=1e-3)
    assert result["peak_jet_speed_m_s"] == pytest.approx(
        result["peak_speed_mm_s"] * ratio / 1000.0, rel=1e-3)


def test_video_ignores_the_report_plots_in_a_measure_folder(tmp_path):
    """A measure folder holds the annotated frames AND the curves, which are a
    different size. VideoWriter is fixed at one size, so feeding it both makes
    every frame after the first garbage."""
    from pathlib import Path

    from hsc import make_video

    src = make_folder(tmp_path)
    mp.measure_folder(src, dest_base=tmp_path / "measure", mm_per_px=MM_PER_PX)
    dest = tmp_path / "measure" / src.name

    images = [p for p in dest.iterdir() if p.suffix.lower() in (".bmp", ".png")]
    frames = make_video.list_frames(dest)
    assert len(images) > len(frames), "the plots were not excluded"
    assert {make_video._frame_size(p) for p in frames} == {(320, 240)}
    assert all(p.name.startswith("frame_") for p in frames)

    result = make_video.make_video(dest)
    assert result["frame_count"] == len(frames)
    assert Path(result["out_path"]).parent == dest
    assert Path(result["out_path"]).name.startswith(dest.name)


def test_plot_helper_renders_an_image():
    from hsc import piston_plot

    img = piston_plot.line_plot([0, 1, 2, 3], [0.0, 1.5, 3.0, 4.5],
                                title="t", x_label="ms", y_label="mm")
    assert img.ndim == 3 and img.shape[2] == 3
    assert img.std() > 0        # something was actually drawn
