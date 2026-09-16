"""BMP row order: the fast raw readers must honor the biHeight sign.

The IMV SDK saves TOP-DOWN BMPs (biHeight < 0) while cv2.imwrite saves
BOTTOM-UP (biHeight > 0). Regression (2026-07-10 rig session): Monitor-mode
folders (written by frame_writer/cv2) were measured upside down -- the jet
landed ~30 px off the reference line and the user read it as the nozzle
having moved.
"""
import struct

import cv2
import numpy as np

from hsc import injection_extract, measure_angle
from hsc.make_video import _read_bgr


def _asym_image(w=8, h=6):
    """Rows 0..h-1 hold distinct values so a flip is unmistakable."""
    return (np.arange(h, dtype=np.uint8)[:, None] * 10 + 5) * np.ones(
        (h, w), np.uint8)


def _write_top_down_bmp(path, img):
    """Hand-rolled 8-bit BMP with negative biHeight (SDK-style, top-down).

    Width must be a multiple of 4 (no row padding), like the rig's 320.
    """
    h, w = img.shape
    assert w % 4 == 0
    offset = 54 + 256 * 4
    head = b"BM" + struct.pack("<IHHI", offset + w * h, 0, 0, offset)
    head += struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 8, 0, w * h, 0, 0, 256, 0)
    palette = b"".join(struct.pack("<BBBB", i, i, i, 0) for i in range(256))
    path.write_bytes(head + palette + img.tobytes())


def test_load_gray_bottom_up_bmp_not_flipped(tmp_path):
    img = _asym_image()
    p = tmp_path / "bu.bmp"
    assert cv2.imwrite(str(p), img)           # cv2 writes bottom-up
    got = measure_angle.load_gray(p)
    ref = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    np.testing.assert_array_equal(got, ref)
    np.testing.assert_array_equal(got, img)


def test_load_gray_top_down_bmp(tmp_path):
    img = _asym_image()
    p = tmp_path / "td.bmp"
    _write_top_down_bmp(p, img)
    np.testing.assert_array_equal(measure_angle.load_gray(p), img)


def test_raw_downsample_getter_orientation(tmp_path):
    img = _asym_image(w=8, h=8)
    p = tmp_path / "frame_000001.bmp"
    assert cv2.imwrite(str(p), img)
    files = injection_extract.list_frames(tmp_path)
    get = injection_extract.raw_downsample_getter(files)
    assert get is not None
    np.testing.assert_array_equal(
        get(0), img[:: injection_extract.DOWNSAMPLE,
                    :: injection_extract.DOWNSAMPLE].astype(np.int16))


def test_make_video_fallback_orientation(tmp_path, monkeypatch):
    img = _asym_image()
    p = tmp_path / "frame_000001.bmp"
    assert cv2.imwrite(str(p), img)
    import hsc.make_video as mv
    monkeypatch.setattr(mv.cv2, "imread",
                        lambda *_a, **_k: None)   # force the raw fallback
    got = _read_bgr(p)
    np.testing.assert_array_equal(got[:, :, 0], img)


def test_motion_signal_backends_agree_on_cv2_bmps(tmp_path):
    """Counts are flip-invariant, but the raw and PIL back-ends must still
    agree frame-for-frame on bottom-up (cv2-written) bursts."""
    rng = np.random.default_rng(3)
    files = []
    for i in range(6):
        img = np.zeros((16, 16), np.uint8)
        if i >= 3:
            img[2:10, 2:14] = rng.integers(100, 255, (8, 12), np.uint8)
        p = tmp_path / f"frame_{i:06d}.bmp"
        assert cv2.imwrite(str(p), img)
        files.append(p)
    files = injection_extract.list_frames(tmp_path)
    raw = injection_extract.compute_motion_signal_raw(files)
    pil = injection_extract.compute_motion_signal(files)
    np.testing.assert_allclose(raw, pil)
