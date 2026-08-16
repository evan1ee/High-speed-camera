"""Every module must import without a camera attached (SDK loads lazily).

``hsc.monitor`` and ``hsc.frame_writer`` lost their only importer when the Tk
app was deleted -- nothing starts a monitoring session until the web UI grows
one -- so this list is what keeps them from rotting unnoticed.
"""
import importlib

import pytest

MODULES = [
    "hsc.app_paths",
    "hsc.calibrate_scale",
    "hsc.capture_image",
    "hsc.frame_writer",
    "hsc.injection_extract",
    "hsc.make_video",
    "hsc.measure_angle",
    "hsc.measure_block",
    "hsc.monitor",
    "hsc.reference_lines",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    assert importlib.import_module(name) is not None
