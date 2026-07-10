"""Wiring tests for MonitorMixin: event/save/stop handlers + the chain pump.

Binds the REAL methods onto a display-free stub, so regressions in the
save-before-process ordering or the one-event-at-a-time pump are caught
without a Tk root or a camera.
"""
from hsc.gui.monitor import MonitorMixin


class _FakeWidget:
    def __init__(self):
        self.configured = []

    def configure(self, **kwargs):
        self.configured.append(kwargs)


class _FakeVar:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _FakeThread:
    def __init__(self, alive):
        self._alive = alive

    def is_alive(self):
        return self._alive


class _Gui:
    """Exactly what the monitor handlers touch; real methods borrowed."""

    _on_monitor_event = MonitorMixin._on_monitor_event
    _on_monitor_saved = MonitorMixin._on_monitor_saved
    _on_monitor_stopped = MonitorMixin._on_monitor_stopped
    _pump_monitor_chain = MonitorMixin._pump_monitor_chain
    _reset_monitor_ui = MonitorMixin._reset_monitor_ui
    MONITOR_DISABLED_BUTTONS = ("run_button",)

    def __init__(self, busy=False):
        import threading
        self.status_var = _FakeVar()
        self.monitor_button = _FakeWidget()
        self.run_button = _FakeWidget()
        self.monitor_active = True
        self.monitor_stop = threading.Event()
        self.monitor_requested = threading.Event()
        self.auto_measure_pending = False
        self._pipeline_t0 = None
        self._monitor_results = {}
        self._monitor_chain = []
        self._monitor_chain_active = False
        self.extract_thread = None
        self.measure_thread = _FakeThread(busy)
        self.video_thread = None
        self.logged = []
        self.dispatched = []

    def _append_log(self, text):
        self.logged.append(text)

    def _on_extract_done(self, result):
        self.dispatched.append(result)


def _result(dest):
    return {"dest_dir": dest, "copy_start_frame": "frame_000001.bmp"}


def test_event_is_held_until_saved_ok_then_processed():
    g = _Gui()
    r = _result("inj/monitor_1")
    g._on_monitor_event(r)
    assert g.dispatched == [] and g._monitor_chain == []   # not yet on disk

    g._on_monitor_saved(("inj/monitor_1", True, "saved 42 frames"))
    assert g.dispatched == [r]                              # processed
    assert g.auto_measure_pending is True
    assert g._monitor_chain_active is True                  # video will be skipped
    assert g._pipeline_t0 is not None


def test_failed_save_drops_the_event():
    g = _Gui()
    g._on_monitor_event(_result("inj/monitor_1"))
    g._on_monitor_saved(("inj/monitor_1", False, "disk full"))
    assert g.dispatched == [] and g._monitor_chain == []
    assert any("disk full" in t for t in g.logged)


def test_pump_queues_while_busy_and_is_fifo():
    g = _Gui(busy=True)
    for k in (1, 2):
        r = _result(f"inj/monitor_{k}")
        g._on_monitor_event(r)
        g._on_monitor_saved((r["dest_dir"], True, "saved"))
    assert g.dispatched == []                # measure thread busy: queued
    assert len(g._monitor_chain) == 2

    g.measure_thread = _FakeThread(False)    # chain step finished
    g._pump_monitor_chain()
    assert [r["dest_dir"] for r in g.dispatched] == ["inj/monitor_1"]
    g._pump_monitor_chain()                  # next VIDEO_DONE re-pump
    assert [r["dest_dir"] for r in g.dispatched] == ["inj/monitor_1",
                                                     "inj/monitor_2"]
    assert g._monitor_chain == []


def test_monitor_stopped_resets_ui_and_pumps():
    g = _Gui()
    g._monitor_chain.append(_result("inj/monitor_1"))
    g._on_monitor_stopped("Monitoring stopped: 1 injection(s), 999 frames examined.")
    assert g.monitor_active is False
    assert g.dispatched != []                # queued event still processed
    assert {"text": "Start Monitoring", "state": "normal"} in [
        {k: str(v) for k, v in c.items()} for c in g.monitor_button.configured
    ]


def test_reset_monitor_ui_is_idempotent():
    g = _Gui()
    g._reset_monitor_ui()
    g._reset_monitor_ui()
    assert g.monitor_active is False
    assert not g.monitor_stop.is_set() and not g.monitor_requested.is_set()


def test_measure_chain_skips_video_for_monitor_events():
    """Monitor mode makes no slow-motion video: after a monitor event's
    measurement, the chain must pump the next event instead of _make_video."""
    from hsc.gui.measurement import MeasurementMixin

    class _M:
        _maybe_auto_video_after_measure = (
            MeasurementMixin._maybe_auto_video_after_measure)

        def __init__(self, monitor_event):
            self.auto_measure_pending = True
            self._monitor_chain_active = monitor_event
            self.last_injection_dir = "inj/run"
            self.calls = []

        def _pump_monitor_chain(self):
            self.calls.append("pump")

        def _make_video(self, source):
            self.calls.append(("video", source))

    m = _M(monitor_event=True)
    m._maybe_auto_video_after_measure()
    assert m.calls == ["pump"]
    assert m.auto_measure_pending is False
    assert m._monitor_chain_active is False

    c = _M(monitor_event=False)          # normal capture chain: video as before
    c._maybe_auto_video_after_measure()
    assert c.calls == [("video", "inj/run")]
