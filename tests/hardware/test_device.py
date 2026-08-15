"""The value types the rig layer passes around, independent of any SDK."""
import numpy as np
import pytest

from hsc.hardware.device import CameraConfigError, CaptureConfig, Frame


def test_frame_exposes_size_and_timing():
    pixels = np.zeros((4, 8), dtype=np.uint8)
    frame = Frame(width=8, height=4, block_id=7, timestamp=1234, pixels=pixels)
    assert (frame.width, frame.height) == (8, 4)
    assert frame.block_id == 7
    assert frame.timestamp == 1234
    assert frame.shape == (4, 8)


def test_frame_is_immutable():
    frame = Frame(8, 4, 0, 0, np.zeros((4, 8), dtype=np.uint8))
    with pytest.raises(AttributeError):
        frame.width = 9


def test_capture_config_rejects_a_size_the_sensor_cannot_produce():
    """Width and height must follow the camera's 4 px increment; a request the
    sensor silently rounds is how a burst ends up a different size than the
    calibration it will be measured against."""
    with pytest.raises(CameraConfigError, match="multiple of 4"):
        CaptureConfig(width=321, height=120, exposure_us=500.0)


def test_capture_config_rejects_a_non_positive_exposure():
    with pytest.raises(CameraConfigError, match="exposure"):
        CaptureConfig(width=320, height=120, exposure_us=0.0)


def test_capture_config_defaults_match_the_rig():
    cfg = CaptureConfig(width=320, height=120, exposure_us=500.0)
    assert cfg.pixel_format == "Mono8"
    assert cfg.center_roi is True
    assert cfg.frame_rate is None      # the camera free-runs; see CLAUDE.md
