#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Run-folder naming and report naming -- the analysis-side rules that used to
be asserted from inside the Tk wiring tests.

None of this needs a camera or a GUI: a run folder's name is built by
``capture_image``, made unique by ``injection_extract.make_dest_dir``, and each
report is named after the folder it lands in so a file copied out of that
folder still identifies its run.
"""
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

from hsc import capture_image, injection_extract, make_video
from hsc import measure_angle, measure_piston


def test_run_folder_timestamp_format():
    args = SimpleNamespace(no_save=False, timestamp_dir=True, aspect="320x240")
    name = capture_image.make_run_output_dir(Path("base"), args).name
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}_320x240", name)


def test_run_label_reaches_every_run_folder():
    """The operator's label (injector SN, dose) rides into the burst folder,
    and from there into injection/measure via make_dest_dir."""
    args = SimpleNamespace(no_save=False, timestamp_dir=True, aspect="320x240",
                           label="SN123 0.5mL")
    name = capture_image.make_run_output_dir(Path("base"), args).name
    assert name.endswith("_SN123-0.5mL"), name
    assert "320x240" in name

    # No label -> unchanged, so existing folders keep their shape.
    args.label = ""
    assert capture_image.make_run_output_dir(Path("base"), args).name.endswith(
        "_320x240")


def test_run_label_is_sanitised_for_windows_paths():
    assert capture_image.safe_label(r'SN<1>:"2"/3\4|5?6*7') == "SN1234567"
    assert capture_image.safe_label("  spaced  out  ") == "spaced-out"
    assert capture_image.safe_label("...") == ""
    assert capture_image.safe_label(None) == ""
    assert len(capture_image.safe_label("x" * 200)) == capture_image.LABEL_MAX
    # Piston/monitor folder names go through the same helper.
    assert capture_image.with_label("run", "") == "run"
    assert capture_image.with_label("run", "a b") == "run_a-b"


def test_aspect_presets_resolve_to_their_own_name():
    """Every ``WxH`` preset really is W by H -- the capture ROI is chosen by
    name, and a preset that disagreed with its name would silently capture at
    a size the stored calibration was not made at."""
    for name, (width, height) in capture_image.ASPECT_PRESETS.items():
        if re.fullmatch(r"\d+x\d+", name):
            assert f"{width}x{height}" == name


def test_reports_are_named_after_their_folder():
    """A CSV, plot or video copied out of its folder still names its run."""
    dest = Path("data/measure/piston_2026-08-12_320x240_SN1")
    assert measure_piston.output_path(dest, measure_piston.CSV_SUFFIX).name == \
        "piston_2026-08-12_320x240_SN1_speed.csv"
    assert "dest_dir.name" in inspect.getsource(measure_angle.measure_folder)
    assert "source_dir.name" in inspect.getsource(make_video.make_video)


def test_make_dest_dir_unique_within_one_second(tmp_path):
    """Run stamps are second-resolution, so two events closing in the same
    second must still get distinct folders (the old single _HHMMSS-suffix
    fallback collided with itself)."""
    made = set()
    for _ in range(3):
        d = injection_extract.make_dest_dir(
            "monitor_2026-07-13-10-00-00_320x240", tmp_path)
        assert d not in made and not d.exists()
        d.mkdir()
        made.add(d)
