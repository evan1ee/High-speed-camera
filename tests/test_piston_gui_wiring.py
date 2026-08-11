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


def test_piston_capture_is_pinned_to_320x240():
    """mm/px is calibrated at this ROI, so a piston burst at any other size
    would be measured against the wrong magnification."""
    from hsc import capture_image
    from hsc.gui.config import PISTON_ASPECT

    assert capture_image.ASPECT_PRESETS[PISTON_ASPECT] == (320, 240)
    src = inspect.getsource(PistonMixin._capture_piston)
    assert "capture_image.ASPECT_PRESETS[PISTON_ASPECT]" in src
    assert "aspect=PISTON_ASPECT" in src
    # Size must not come from the aspect selector.
    assert "base.width" not in src and "base.height" not in src


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
