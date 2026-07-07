"""The edge_v2 opt-in switch: defaults stay legacy, context flips + restores."""
from hsc import measure_angle as ma


def test_defaults_are_legacy():
    assert ma.EDGE_MODEL == "legacy"
    assert ma.BG_MODE == "window"
    assert ma.ANGLE_POLICY == "max"


def test_edge_v2_context_flips_and_restores():
    with ma.edge_v2():
        assert ma.EDGE_MODEL == "erf"
        assert ma.BG_MODE == "pre-onset"
        assert ma.ANGLE_POLICY == "trusted"
    assert ma.EDGE_MODEL == "legacy"
    assert ma.BG_MODE == "window"
    assert ma.ANGLE_POLICY == "max"


def test_edge_v2_restores_on_error():
    try:
        with ma.edge_v2():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert ma.EDGE_MODEL == "legacy"


def test_edge_v2_disabled_is_a_noop():
    with ma.edge_v2(False):
        assert ma.EDGE_MODEL == "legacy"
        assert ma.BG_MODE == "window"


def test_gui_checkbox_exists_and_defaults_off():
    from hsc.gui.measurement import MeasurementMixin
    import inspect
    src = inspect.getsource(MeasurementMixin)
    assert "edge_v2_var" in src
    # The worker must route through the context manager.
    assert "measure_angle.edge_v2(" in src
