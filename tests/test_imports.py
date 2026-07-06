"""Every module must import without a camera attached (SDK loads lazily)."""
import importlib

import pytest

MODULES = [
    "app_paths",
    "calibrate_scale",
    "calibrate_ui",
    "capture_gui",
    "capture_image",
    "injection_extract",
    "make_video",
    "measure_angle",
    "measure_block",
    "reference_lines",
    "reference_ui",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    assert importlib.import_module(name) is not None
