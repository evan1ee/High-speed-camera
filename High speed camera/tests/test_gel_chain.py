"""Wiring for the Capture Gel Injection chain: capture -> find -> video.

A jet fired into a gel block leaves the scene permanently changed and has no
free jet to measure an angle on, so this chain differs from the spray one in
exactly two places. Both are pinned here, structurally, so a refactor that
drops either is caught without a Tk root or a camera.
"""
import inspect

from hsc.gui import capture, extraction, gel, layout, monitor


def test_the_button_exists_in_the_operation_section():
    src = inspect.getsource(layout)
    assert "Capture Gel Injection" in src
    assert "self.gel_button" in src
    assert "command=self._capture_gel" in src
    # Gridded with the other Operation buttons, not left unplaced.
    assert "self.gel_button, self.open_button" in src


def test_the_gel_capture_forces_smart_save_off_and_marks_the_run():
    """Smart save plans its window with the presence rule -- the very rule this
    path avoids -- so it must not run; and the folder is identifiable on disk."""
    src = inspect.getsource(gel.GelMixin._capture_gel)
    assert "params.smart_save = False" in src
    assert 'params.run_prefix = "gel"' in src
    assert "self.gel_chain = True" in src


def test_the_chain_skips_measure_and_uses_the_temporal_end_rule():
    src = inspect.getsource(capture.CaptureMixin._on_capture_done)
    assert "self.auto_measure_pending = not self.gel_chain" in src
    assert 'end_rule="temporal"' in src


def test_extraction_routes_a_gel_run_to_the_video_not_the_measure():
    src = inspect.getsource(extraction.ExtractionMixin._on_extract_done)
    assert "self.gel_chain" in src
    assert "self._make_video(self.last_injection_dir)" in src
    # The flag is cleared so a later manual Find Injection does not chain.
    assert "self.gel_chain = False" in src


def test_end_rule_reaches_extract_injection():
    find_src = inspect.getsource(extraction.ExtractionMixin._find_injection)
    worker_src = inspect.getsource(extraction.ExtractionMixin._extract_worker)
    assert "end_rule" in find_src
    assert "end_rule=end_rule" in worker_src


def test_a_failed_capture_or_extraction_clears_the_chain():
    """Otherwise the next manual Find Injection would silently make a video."""
    assert "self.gel_chain = False" in inspect.getsource(
        capture.CaptureMixin._on_capture_error)
    assert "self.gel_chain = False" in inspect.getsource(
        extraction.ExtractionMixin._on_extract_error)


def test_the_gel_button_is_camera_owning():
    """Monitor mode disables every button that would fight it for the camera."""
    assert "gel_button" in monitor.MonitorMixin.MONITOR_DISABLED_BUTTONS
    # And a dying camera returns the toggle to idle.
    assert "_reset_gel_ui()" in inspect.getsource(capture.CaptureMixin)


def test_the_mixin_is_assembled_into_the_app():
    from hsc.gui.app import CaptureGui
    assert gel.GelMixin in CaptureGui.__mro__
    assert "_init_gel_state" in inspect.getsource(CaptureGui.__init__)
