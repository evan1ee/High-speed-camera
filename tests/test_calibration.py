"""The stored rig calibration must remain loadable after every move."""


def test_load_calibration_found():
    import calibrate_scale

    cal = calibrate_scale.load_calibration()
    assert cal is not None
    assert cal["mm_per_px"] > 0
