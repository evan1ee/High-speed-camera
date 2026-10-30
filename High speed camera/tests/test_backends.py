"""All three motion-signal back-ends must produce the *same* signal.

Generates a tiny synthetic burst of uncompressed 8-bit BMPs (a moving bright
blob) and asserts the NumPy raw-BMP reader and the PIL reader agree exactly,
and -- when the compiled scanner is present -- that it agrees too.
"""
import cv2
import numpy as np
import pytest

from hsc import injection_extract


def _write_burst(tmp_path, n=8, w=32, h=24):
    """Write n frames (width a multiple of 4 -> no BMP row padding) of a bright
    square sliding across a dark background. Returns the sorted file list."""
    files = []
    for i in range(n):
        img = np.full((h, w), 10, np.uint8)
        x = 2 + i * 3
        img[8:16, x : x + 6] = 220
        path = tmp_path / f"frame_{i:06d}.bmp"
        assert cv2.imwrite(str(path), img)
        files.append(path)
    return injection_extract.list_frames(tmp_path)


def test_bmp_parseable(tmp_path):
    files = _write_burst(tmp_path)
    info = injection_extract._bmp_info(files[0])
    assert info is not None
    assert info[3] == 8  # 8-bit


def test_raw_matches_pil(tmp_path):
    files = _write_burst(tmp_path)
    raw = injection_extract.compute_motion_signal_raw(files)
    pil = injection_extract.compute_motion_signal(files)
    assert raw is not None
    assert np.array_equal(raw, pil)
    # Sanity: a moving blob actually produces motion after the first frame.
    assert raw[0] == 0
    assert raw[1:].sum() > 0


def test_cpp_matches_python(tmp_path):
    if not injection_extract.CPP_EXE.exists():
        pytest.skip("compiled scanner not present")
    files = _write_burst(tmp_path)
    cpp = injection_extract.scan_with_cpp(files[0].parent, len(files))
    if cpp is None:
        pytest.skip("scanner declined this input (returned None)")
    pil = injection_extract.compute_motion_signal(files)
    assert np.array_equal(cpp, pil)
