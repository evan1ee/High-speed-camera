"""The stored rig calibration must remain loadable after every move."""

import pytest

from hsc.app_paths import data_root


def test_load_calibration_found():
    if not (data_root() / "calibration.json").is_file():
        pytest.skip("no rig calibration on this machine (data/ is gitignored)")

    from hsc import calibrate_scale

    cal = calibrate_scale.load_calibration()
    assert cal is not None
    assert cal["mm_per_px"] > 0
