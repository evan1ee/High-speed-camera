"""Every module must import without a camera attached (SDK loads lazily)."""
import importlib

import pytest

MODULES = [
    "hsc.app_paths",
    "hsc.calibrate_scale",
    "hsc.calibrate_ui",
    "hsc.capture_gui",
    "hsc.capture_image",
    "hsc.gui",
    "hsc.gui.app",
    "hsc.gui.calibration",
    "hsc.gui.camera_worker",
    "hsc.gui.capture",
    "hsc.gui.config",
    "hsc.gui.extraction",
    "hsc.gui.layout",
    "hsc.gui.measurement",
    "hsc.gui.reference",
    "hsc.gui.selftest",
    "hsc.gui.video",
    "hsc.injection_extract",
    "hsc.make_video",
    "hsc.measure_angle",
    "hsc.measure_block",
    "hsc.reference_lines",
    "hsc.reference_ui",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    assert importlib.import_module(name) is not None
