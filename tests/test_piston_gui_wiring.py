"""Wiring checks for the piston feature (no display, no camera needed).

The piston pipeline shares the camera thread and the button sections with the
spray pipeline, so these guard the seams: that its queue kinds are dispatched,
that its buttons exist in the right sections, that a dying camera cannot
strand the Capture Piston toggle, and -- most importantly -- that the tuned
spray capture path was left alone.
"""

import inspect

import hsc.gui.camera_worker as camera_worker
import hsc.gui.capture as capture
import hsc.gui.layout as layout
import hsc.gui.monitor as monitor
from hsc.gui.app import CaptureGui
from hsc.gui.piston import PistonMixin


def test_piston_mixin_is_assembled_into_the_window():
    assert PistonMixin in CaptureGui.__mro__
    assert "self._init_piston_state()" in inspect.getsource(CaptureGui.__init__)


def test_piston_queue_handlers_resolve():
    for kind, name in PistonMixin.QUEUE_HANDLERS.items():
        assert callable(getattr(CaptureGui, name, None)), kind


def test_piston_buttons_live_in_the_expected_sections():
    src = inspect.getsource(layout)
    assert 'operation, text="Capture Piston"' in src
    assert 'workflow, text="Find Injection Piston"' in src
    assert 'workflow, text="Measure Piston"' in src
    assert 'self._label_entry(workflow, "Piston FPS (if no meta)"' in src


def test_camera_worker_serves_piston_requests():
    src = inspect.getsource(camera_worker)
    assert "self.piston_requested.is_set()" in src
    assert "_do_piston_capture" in src


def test_piston_capture_does_not_touch_the_spray_capture_path():
    """The spray burst is heavily tuned; the piston run must be its own loop
    rather than another branch inside _do_capture."""
    spray = inspect.getsource(camera_worker.CameraWorkerMixin._do_capture)
    assert "piston" not in spray.lower()


def test_piston_capture_records_frame_timing():
    """Without per-frame timestamps there is no honest speed axis."""
    src = inspect.getsource(camera_worker.CameraWorkerMixin._do_piston_capture)
    assert "frameInfo.timeStamp" in src
    assert "frameInfo.blockId" in src
    assert "frame_times_us" in src
    assert "CAPTURE_META_NAME" in src


def test_capture_rois_are_selectable_and_resolve():
    """Three ROIs, all 320 wide -- the frame rate is bound by row readout, so
    only the height varies."""
    from hsc import capture_image
    from hsc.gui.config import CAPTURE_ROIS, DEFAULT_ROI, ROI_FPS

    assert DEFAULT_ROI in CAPTURE_ROIS
    assert set(CAPTURE_ROIS) == set(ROI_FPS)
    heights = []
    for roi in CAPTURE_ROIS:
        width, height = capture_image.ASPECT_PRESETS[roi]
        assert width == 320
        assert f"{width}x{height}" == roi
        heights.append(height)
    # Shorter ROI => higher rate.
    rates = [ROI_FPS[r] for r in CAPTURE_ROIS]
    assert sorted(heights, reverse=True) == heights
    assert sorted(rates) == rates


def test_piston_capture_uses_the_selected_roi():
    src = inspect.getsource(PistonMixin._capture_piston)
    assert "self.aspect_var.get()" in src
    assert "capture_image.ASPECT_PRESETS[aspect]" in src
    # ... and still records the size it asked for, so the worker can verify it.
    assert "width=width" in src and "height=height" in src


def test_roi_change_restarts_the_preview():
    """The ROI is programmed when the grab thread starts, so a running preview
    keeps streaming the old size until it is restarted."""
    src = inspect.getsource(capture)
    assert "_on_roi_change" in src
    assert "_restart_preview_pending" in src
    layout_src = inspect.getsource(layout)
    assert "values=CAPTURE_ROIS" in layout_src
    assert 'self.roi_combo.bind("<<ComboboxSelected>>"' in layout_src


def test_piston_capture_rejects_a_wrong_frame_size():
    """Pinning the params is not enough -- the camera could still be streaming
    another ROI (e.g. the preview was started before the setting changed)."""
    src = inspect.getsource(camera_worker.CameraWorkerMixin._do_piston_capture)
    assert "frame.frameInfo.width" in src and "frame.frameInfo.height" in src
    assert "(params.width, params.height)" in src
    assert "raise RuntimeError(" in src


def test_find_piston_v2_checkbox_is_wired():
    """The V2 checkbox must actually reach extract_piston_event; a checkbox
    that only changes a log line is worse than none."""
    assert "piston_v2_var" in inspect.getsource(PistonMixin._init_piston_state)
    assert '("Find piston V2", self.piston_v2_var, None)' in inspect.getsource(layout)
    find = inspect.getsource(PistonMixin._find_piston_injection)
    assert "self.piston_v2_var.get()" in find
    worker = inspect.getsource(PistonMixin._piston_find_worker)
    assert "fast=fast" in worker


def test_run_label_reaches_every_run_folder():
    """The operator's label (injector SN, dose) rides into the burst folder,
    and from there into injection/measure via make_dest_dir."""
    from pathlib import Path
    from types import SimpleNamespace

    from hsc import capture_image

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
    from hsc import capture_image

    assert capture_image.safe_label(r'SN<1>:"2"/3\4|5?6*7') == "SN1234567"
    assert capture_image.safe_label("  spaced  out  ") == "spaced-out"
    assert capture_image.safe_label("...") == ""
    assert capture_image.safe_label(None) == ""
    assert len(capture_image.safe_label("x" * 200)) == capture_image.LABEL_MAX
    # Piston/monitor folder names go through the same helper.
    assert capture_image.with_label("run", "") == "run"
    assert capture_image.with_label("run", "a b") == "run_a-b"


def test_reports_are_named_after_their_folder():
    """A CSV, plot or video copied out of its folder still names its run."""
    from pathlib import Path

    from hsc import measure_piston as mp

    dest = Path("data/measure/piston_2026-08-12_320x240_SN1")
    assert mp.output_path(dest, mp.CSV_SUFFIX).name == \
        "piston_2026-08-12_320x240_SN1_speed.csv"
    assert "dest_dir.name" in inspect.getsource(
        __import__("hsc.measure_angle", fromlist=["measure_folder"]).measure_folder)
    assert "source_dir.name" in inspect.getsource(
        __import__("hsc.make_video", fromlist=["make_video"]).make_video)


def test_dead_camera_releases_the_piston_toggle():
    assert "self._reset_piston_ui()" in inspect.getsource(capture)


def test_camera_owning_buttons_are_mutually_exclusive():
    assert "piston_button" in monitor.MonitorMixin.MONITOR_DISABLED_BUTTONS
    assert "self.piston_requested.is_set()" in inspect.getsource(monitor)
    assert "Finish the piston capture first." in inspect.getsource(capture)


def test_piston_chain_skips_the_slow_motion_video():
    """Monitor mode already proved the video is unwanted for repeat runs;
    the piston chain is capture -> find -> measure only."""
    src = inspect.getsource(PistonMixin)
    assert "_make_video" not in src
    assert "self._find_piston_injection(info[\"dir\"])" in src
    assert "self._measure_piston(self.last_piston_dir)" in src
