"""Wiring checks for the hsc.gui mixin split (no display needed).

Guards the two ways the declarative queue-dispatch can silently break:
a QUEUE_HANDLERS entry naming a method that does not exist, and two mixins
claiming the same message kind.
"""
from hsc.gui.app import CaptureGui


def _handler_maps():
    for klass in CaptureGui.__mro__:
        handlers = vars(klass).get("QUEUE_HANDLERS")
        if handlers:
            yield klass, handlers


def test_queue_handlers_resolve_to_methods():
    for klass, handlers in _handler_maps():
        for kind, name in handlers.items():
            method = getattr(CaptureGui, name, None)
            assert callable(method), (
                f"{klass.__name__}.QUEUE_HANDLERS[{kind!r}] -> {name!r} "
                "does not resolve to a CaptureGui method"
            )


def test_queue_kinds_are_unique_across_mixins():
    seen = {}
    for klass, handlers in _handler_maps():
        for kind in handlers:
            assert kind not in seen, (
                f"Message kind {kind!r} handled by both "
                f"{seen[kind]} and {klass.__name__}"
            )
            seen[kind] = klass.__name__


def test_expected_message_kinds_present():
    """Every message kind the workers post must have a registered handler."""
    expected = {
        "STATUS",
        "CAPTURE_DONE", "CAPTURE_ERROR",
        "EXTRACT_DONE", "EXTRACT_ERROR",
        "MEASURE_DONE", "MEASURE_ERROR",
        "MONITOR_EVENT", "MONITOR_SAVED", "MONITOR_STOPPED",
        "PISTON_CAPTURE_DONE", "PISTON_CAPTURE_ERROR",
        "PFIND_DONE", "PFIND_ERROR", "PMEASURE_DONE", "PMEASURE_ERROR",
        "SUMMARY_DONE", "SUMMARY_ERROR",
        "BLOCK_CAPTURED", "BLOCK_DONE", "BLOCK_ERROR",
        "VIDEO_DONE", "VIDEO_ERROR",
        "SCALE_CAPTURED", "SCALE_DONE", "SCALE_ERROR",
        "MEASBLOCK_CAPTURED", "MEASBLOCK_DONE", "MEASBLOCK_ERROR",
        "REFERENCE_CAPTURED", "REFERENCE_ERROR",
    }
    kinds = set()
    for _, handlers in _handler_maps():
        kinds.update(handlers)
    assert expected <= kinds, f"Missing handlers for: {expected - kinds}"


def test_capture_gui_shim_reexports():
    import hsc.capture_gui as shim

    assert shim.CaptureGui is CaptureGui
    assert callable(shim.main)


def test_defer_and_no_save_checkboxes_removed():
    """Defer save is always on and test-only/no-save is gone: no checkboxes,
    the capture params are hardwired (the worker still honors both fields)."""
    import inspect

    import hsc.gui.capture as capture
    import hsc.gui.layout as layout

    lsrc = inspect.getsource(layout)
    assert "Defer save" not in lsrc
    assert "Test only" not in lsrc
    csrc = inspect.getsource(capture)
    assert "defer_save_var" not in csrc
    assert "no_save_var" not in csrc
    assert "defer_save=True" in csrc
    assert "no_save=False" in csrc


def test_cal_distance_defaults_to_5mm():
    import inspect

    import hsc.gui.calibration as calibration

    assert 'ref_mm_var = tk.StringVar(value="5")' in inspect.getsource(calibration)


def test_timestamp_and_padding_controls_removed():
    """Timestamp folder is always on and before/after padding is fixed at 30:
    no checkbox, no entry fields, no Tk vars read anywhere."""
    import inspect

    import hsc.gui.capture as capture
    import hsc.gui.extraction as extraction
    import hsc.gui.layout as layout
    import hsc.gui.monitor as monitor

    lsrc = inspect.getsource(layout)
    assert "Timestamp folder" not in lsrc
    assert "Frames before injection" not in lsrc
    assert "Frames after injection" not in lsrc
    for mod in (capture, extraction, monitor):
        src = inspect.getsource(mod)
        assert "timestamp_dir_var" not in src, mod.__name__
        assert "before_var" not in src, mod.__name__
        assert "after_var" not in src, mod.__name__
    csrc = inspect.getsource(capture)
    assert "timestamp_dir=True" in csrc


def test_capture_button_is_a_toggle():
    """The separate Stop button is gone; Capture toggles to 'Stop Capture'
    while a burst is running."""
    import inspect

    import hsc.gui.capture as capture
    import hsc.gui.layout as layout

    assert "stop_button" not in inspect.getsource(layout)
    csrc = inspect.getsource(capture)
    assert "stop_button" not in csrc
    assert "Stop Capture" in csrc


def test_run_folder_timestamp_format():
    import re
    from pathlib import Path
    from types import SimpleNamespace

    from hsc import capture_image

    args = SimpleNamespace(no_save=False, timestamp_dir=True, aspect="320x240")
    name = capture_image.make_run_output_dir(Path("base"), args).name
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}_320x240", name)


def test_monitor_folder_timestamp_format():
    import inspect

    import hsc.gui.camera_worker as camera_worker

    src = inspect.getsource(camera_worker)
    assert "%Y-%m-%d-%H-%M-%S" in src
    assert "%Y%m%d_%H%M%S_%f" not in src


def test_button_sections():
    """Buttons are grouped: Operation (preview/capture/monitor), Workflow
    (find injection/measure/video), Initial Setup (calibration/reference/open
    + the Cal. distance field); checkboxes sit in a single row."""
    import inspect

    import hsc.gui.layout as layout

    src = inspect.getsource(layout)
    # Sections in user order: setup first, then workflow, operation last.
    order = [src.index(t) for t in ('section("Initial Setup"',
                                    'section("Workflow"',
                                    'section("Operation"')]
    assert order == sorted(order)
    # Section membership: each button is created with its section as parent.
    assert "operation, text=" in src and "workflow, text=" in src
    assert "setup, text=" in src
    assert "per_row" not in src          # old two-row checkbox layout gone
    # Cal. distance -> Initial Setup; Measure from/to + the checkbox row ->
    # Workflow; Open Last Folder -> Operation.
    assert 'self._label_entry(setup, "Cal. distance (mm)"' in src
    assert 'self._label_entry(\n            workflow, "Measure from (Nth)"' in src
    assert "checks = ttk.Frame(workflow)" in src
    assert 'ttk.Button(\n            operation, text="Open Last Folder"' in src


def test_settings_column_is_scrollable():
    """The left column keeps growing as settings are added; on a laptop screen
    it pushed the Operation buttons and the Output log off the bottom with no
    way to reach them."""
    import inspect

    import hsc.gui.layout as layout

    src = inspect.getsource(layout)
    assert "_scrollable_column" in src
    assert "left = self._scrollable_column(top)" in src
    # Wheel support, and a scrollbar only when the content overflows.
    assert '"<MouseWheel>"' in src
    assert "pack_forget()" in src
    assert "yview_scroll" in src


def test_output_base_folder_is_the_data_root():
    """The folder field shows the data root (captures/injection images/measure
    all live under it); the burst dir derives <field>\\captures from it."""
    import inspect

    import hsc.gui.capture as capture

    src = inspect.getsource(capture)
    assert 'output_dir_var = tk.StringVar(value=str(ROOT))' in src
    assert '/ "captures"' in src


def test_make_dest_dir_unique_within_one_second(tmp_path):
    """Run stamps are second-resolution now, so two monitor events closing in
    the same second must still get distinct folders (the old single
    _HHMMSS-suffix fallback collided with itself)."""
    from hsc import injection_extract

    made = set()
    for _ in range(3):
        d = injection_extract.make_dest_dir("monitor_2026-07-13-10-00-00_320x240",
                                            tmp_path)
        assert d not in made and not d.exists()
        d.mkdir()
        made.add(d)
