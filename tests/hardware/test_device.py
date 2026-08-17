"""The value types the rig layer passes around, independent of any SDK."""
import numpy as np
import pytest

from hsc.hardware.device import (CameraConfigError, CaptureConfig, Frame,
                                  Grab, sdk_device_index)


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


def test_frame_equality_is_by_identity_not_pixel_value():
    """Two distinct frames holding equal pixels are not equal (identity semantics).
    Comparison must return a plain bool, not an ambiguous ndarray."""
    pixels = np.zeros((4, 8), dtype=np.uint8)
    frame1 = Frame(8, 4, 0, 0, pixels)
    frame2 = Frame(8, 4, 0, 0, pixels.copy())
    # Both frames hold identical pixel data, but they are not equal.
    assert frame1 is not frame2
    result = frame1 == frame2
    assert isinstance(result, (bool, np.bool_))
    assert not result


def test_sdk_device_index_translates_the_rigs_first_camera():
    """The rig is 1-based everywhere (capture_image.DEFAULT_CAPTURE_CONFIG,
    capture_once/capture_burst's ``1 <= index <= nDevNum`` validation); the
    SDK's IMV_CreateHandle wants a 0-based index."""
    assert sdk_device_index(1) == 0


def test_sdk_device_index_translates_a_later_camera():
    assert sdk_device_index(3) == 2


def test_sdk_device_index_rejects_the_sdks_own_zero_based_index():
    """Passing 0 (or lower) is the exact mistake this function exists to
    catch -- it would silently open the wrong physical device."""
    with pytest.raises(CameraConfigError, match="1-based"):
        sdk_device_index(0)


def test_sdk_device_index_rejects_a_negative_index():
    with pytest.raises(CameraConfigError, match="1-based"):
        sdk_device_index(-1)


def test_frame_is_hashable():
    """Frame objects are hashable and can be added to sets or used as dict keys."""
    pixels = np.zeros((4, 8), dtype=np.uint8)
    frame = Frame(8, 4, 0, 0, pixels)
    # Should not raise TypeError: unhashable type
    hash_value = hash(frame)
    assert isinstance(hash_value, int)
    # Should be usable in a set
    frame_set = {frame}
    assert frame in frame_set


def test_a_grab_that_matches_the_ok_status_is_ok():
    """The comparison the SDK adapter used to make for itself, in a dict
    lookup the no-logic guard could not see. It lives here now, where it is
    covered -- and where the worker can tell an ended burst from a fault."""
    frame = Frame(8, 4, 1, 0, np.zeros((4, 8), dtype=np.uint8))
    grab = Grab(status=0, ok_status=0, build=lambda: frame)
    assert grab.ok is True
    assert grab.build() is frame


@pytest.mark.parametrize("status", [-3, -101, 1])
def test_any_other_status_is_not_ok_and_carries_no_frame(status):
    """Every non-OK status -- a timeout and a genuine fault alike -- used to
    become None, so the reason a burst ended was thrown away before anyone
    could report it. The value survives now; only ``ok`` is decided."""
    grab = Grab(status=status, ok_status=0)
    assert grab.ok is False
    assert grab.status == status
    assert grab.build is None
