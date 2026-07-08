"""Wiring test for the smart-save dispatch seam in CaptureMixin._on_capture_done.

CAPTURE_DONE hands the GUI a payload dict describing what the camera worker
already did during the save phase. `_on_capture_done` must route it to exactly
one continuation:

    extract_result present  -> _on_extract_done (smart save wrote the window)
    bounds + signal         -> _auto_copy_injection (bounds computed in RAM)
    signal only             -> _auto_extract_from_signal
    (else)                  -> _find_injection

These tests bind the REAL method onto a display-free stub so a regression in
the branch order or the guard is caught without a Tk root or a camera.
"""
from types import SimpleNamespace

from hsc.gui.capture import CaptureMixin


class _FakeWidget:
    """Stand-in for the run/stop buttons: swallows .configure(state=...)."""

    def configure(self, **kwargs):
        pass


class _FakeVar:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _Dispatcher:
    """Minimal object exposing exactly what _on_capture_done touches, plus the
    four continuations recorded instead of executed. Borrows the real method."""

    _on_capture_done = CaptureMixin._on_capture_done

    def __init__(self, no_save=False):
        self.status_var = _FakeVar()
        self.run_button = _FakeWidget()
        self.stop_button = _FakeWidget()
        self.capture_params = SimpleNamespace(no_save=no_save)
        self.last_output_dir = None
        self.auto_measure_pending = False
        self.calls = []

    def _on_extract_done(self, result):
        self.calls.append(("extract_done", result))

    def _auto_copy_injection(self, info):
        self.calls.append(("copy", info))

    def _auto_extract_from_signal(self, files, signal):
        self.calls.append(("extract_from_signal", files, signal))

    def _find_injection(self, source):
        self.calls.append(("find", source))


def test_extract_result_present_routes_to_on_extract_done():
    d = _Dispatcher()
    result = {"dest_dir": "inj/run", "copy_start_frame": "frame_000001.bmp"}
    payload = {
        "dir": "captures/run",
        "extract_result": result,
        "bounds": (10, 20, 15),      # present but must be ignored
        "signal": [0.0, 1.0, 2.0],   # present but must be ignored
        "files": ["a.bmp", "b.bmp"],
    }

    d._on_capture_done(payload)

    assert d.calls == [("extract_done", result)]
    # The exact same dict object is forwarded, not a copy/rebuild.
    assert d.calls[0][1] is result
    assert d.auto_measure_pending is True


def test_bounds_and_signal_route_to_auto_copy():
    d = _Dispatcher()
    payload = {
        "dir": "captures/run",
        "extract_result": None,
        "bounds": (10, 20, 15),
        "signal": [0.0, 1.0, 2.0],
        "files": ["a.bmp", "b.bmp"],
    }

    d._on_capture_done(payload)

    assert d.calls == [("copy", payload)]
    assert d.auto_measure_pending is True


def test_signal_only_routes_to_extract_from_signal():
    d = _Dispatcher()
    files = ["a.bmp", "b.bmp"]
    signal = [0.0, 1.0, 2.0]
    payload = {
        "dir": "captures/run",
        "extract_result": None,
        "bounds": None,
        "signal": signal,
        "files": files,
    }

    d._on_capture_done(payload)

    assert d.calls == [("extract_from_signal", files, signal)]
    assert d.auto_measure_pending is True


def test_no_signal_falls_back_to_find_injection():
    d = _Dispatcher()
    payload = {
        "dir": "captures/run",
        "extract_result": None,
        "bounds": None,
        "signal": [],
    }

    d._on_capture_done(payload)

    assert d.calls == [("find", "captures/run")]
    assert d.auto_measure_pending is True


def test_no_save_skips_the_whole_chain():
    d = _Dispatcher(no_save=True)
    payload = {
        "dir": "captures/run",
        "extract_result": {"dest_dir": "inj/run"},
        "bounds": (10, 20, 15),
        "signal": [0.0, 1.0, 2.0],
        "files": ["a.bmp"],
    }

    d._on_capture_done(payload)

    assert d.calls == []
    assert d.auto_measure_pending is False
