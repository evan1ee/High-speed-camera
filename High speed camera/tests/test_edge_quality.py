"""Per-edge quality scores and the trusted-edge angle policy."""
from hsc import measure_angle as ma


def test_edge_quality_combines_rms_and_confidence():
    good = ma.edge_quality(rms=0.15, edge_conf=0.95)
    bad_fit = ma.edge_quality(rms=1.2, edge_conf=0.95)
    bad_conf = ma.edge_quality(rms=0.15, edge_conf=0.05)
    assert good > 75
    assert bad_fit < 25 and bad_conf < 25


def test_resolve_angle_max_policy_is_legacy():
    old = ma.ANGLE_POLICY
    try:
        ma.ANGLE_POLICY = "max"
        angle, policy = ma.resolve_angle(0.5, 2.0, "High", "Low")
        assert angle == 2.0 and policy == "max"
    finally:
        ma.ANGLE_POLICY = old


def test_resolve_angle_trusted_policy_drops_the_bad_edge():
    old = ma.ANGLE_POLICY
    try:
        ma.ANGLE_POLICY = "trusted"
        angle, policy = ma.resolve_angle(0.5, 2.0, "High", "Low")
        assert angle == 0.5 and policy == "upper-only"
        angle, policy = ma.resolve_angle(2.0, 0.5, "Low", "Medium")
        assert angle == 0.5 and policy == "lower-only"
        # Both trusted (or both untrusted): fall back to max.
        angle, policy = ma.resolve_angle(0.5, 2.0, "High", "High")
        assert angle == 2.0 and policy == "max"
        angle, policy = ma.resolve_angle(0.5, 2.0, "Low", "Low")
        assert angle == 2.0 and policy == "max"
    finally:
        ma.ANGLE_POLICY = old
