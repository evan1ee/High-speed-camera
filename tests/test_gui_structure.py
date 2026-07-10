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
