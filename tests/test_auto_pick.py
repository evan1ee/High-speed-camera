"""Auto-pick measure mode: find the first run of AUTO_PICK_COUNT consecutive
measurable frames whose jet span is stable, instead of fixed start..end."""
from hsc import measure_angle as ma


def test_stable_window_skips_growing_burst():
    # Burst grows (unstable), then the jet settles: pick the first stable run.
    spans = [50.0, 120.0, 190.0, 240.0, 270.0,          # growing burst
             284.0, 285.0, 286.0, 284.0, 285.0, 285.0]  # steady
    idx = ma.find_stable_window(spans, count=5, tol=0.05)
    assert idx == 5


def test_stable_window_requires_consecutive_frames():
    # A None (unmeasurable frame) breaks the run.
    spans = [284.0, 285.0, None, 284.0, 285.0, 286.0, 284.0, 285.0]
    idx = ma.find_stable_window(spans, count=5, tol=0.05)
    assert idx == 3


def test_stable_window_none_when_unstable():
    spans = [100.0, 200.0, 100.0, 200.0, 100.0, 200.0]
    assert ma.find_stable_window(spans, count=5, tol=0.05) is None


def test_stable_window_rejects_unstable_angle():
    # A fast jet reaches full span immediately, so the burst frames have a
    # stable SPAN but a wildly varying ANGLE -- they must not be picked.
    spans = [285.0] * 10
    angles = [6.2, 3.9, 2.8, 2.2, 1.8,            # burst: angle settling
              1.25, 1.22, 1.24, 1.21, 1.23]       # steady
    idx = ma.find_stable_window(spans, angles=angles, count=5, tol=0.05)
    assert idx == 5


def test_gui_wiring_auto_pick():
    import inspect
    from hsc.gui.measurement import MeasurementMixin
    from hsc.gui.layout import LayoutMixin

    msrc = inspect.getsource(MeasurementMixin)
    assert "auto_pick_var" in msrc
    assert "auto_pick=" in msrc            # routed into measure_folder
    assert "_toggle_auto_pick" in msrc     # entries enabled/disabled
    lsrc = inspect.getsource(LayoutMixin)
    assert "auto_pick_var" in lsrc
    assert "measure_start_entry" in lsrc   # entry handles kept for disabling
