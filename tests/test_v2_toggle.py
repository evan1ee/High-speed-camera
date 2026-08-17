"""The edge_v2 opt-in switch: defaults stay legacy, context flips + restores."""
from hsc import measure_angle as ma


def test_defaults_are_legacy():
    assert ma.EDGE_MODEL == "legacy"
    # pre-onset is the default since the window-median background erases a
    # steady jet and derails frame selection; it falls back to the window
    # median when injection_meta.json is absent, so meta-less folders (and the
    # benchmark wedges) still measure exactly as legacy.
    assert ma.BG_MODE == "pre-onset"
    assert ma.ANGLE_POLICY == "max"


def test_edge_v2_context_flips_and_restores():
    with ma.edge_v2():
        assert ma.EDGE_MODEL == "erf"
        assert ma.BG_MODE == "pre-onset"
        assert ma.ANGLE_POLICY == "trusted"
    assert ma.EDGE_MODEL == "legacy"
    assert ma.BG_MODE == "pre-onset"
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
        assert ma.BG_MODE == "pre-onset"


def test_v2_flags_are_exactly_the_three_switched_together():
    """``V2_FLAGS`` is the contract a caller reads to know what edge_v2()
    changes; it must not drift from what the context manager actually flips."""
    assert set(ma.V2_FLAGS) == {"EDGE_MODEL", "BG_MODE", "ANGLE_POLICY"}
    before = {name: getattr(ma, name) for name in ma.V2_FLAGS}
    with ma.edge_v2():
        during = {name: getattr(ma, name) for name in ma.V2_FLAGS}
    assert {n for n in ma.V2_FLAGS if before[n] != during[n]} == {
        "EDGE_MODEL", "ANGLE_POLICY"}
