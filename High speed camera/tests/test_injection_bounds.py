"""Characterization tests for the injection-bounds detection + copy window.

These exercise the real functions the GUI/CLI rely on (``detect_injection_bounds``
and ``build_result``) on a synthetic motion signal: flat low noise with a clear
spike burst. Assertions are generous -- current behavior is correct, this guards
against regressions in the onset/threshold walk and the copy-window clamping.
"""
from pathlib import Path

import numpy as np
import pytest

from hsc import injection_extract


BURST_LO = 200
BURST_HI = 230
N = 500


def _make_signal():
    rng = np.random.default_rng(0)
    signal = rng.uniform(0.0, 15.0, size=N)  # flat low noise, below abs_floor=30
    # A clear triangular burst peaking near the middle of [BURST_LO, BURST_HI).
    for i in range(BURST_LO, BURST_HI):
        frac = 1.0 - abs((i - (BURST_LO + BURST_HI) / 2)) / ((BURST_HI - BURST_LO) / 2)
        signal[i] = 800.0 + 2500.0 * frac
    return signal


def test_detect_bounds_covers_the_spike():
    signal = _make_signal()
    bounds = injection_extract.detect_injection_bounds(signal)
    assert bounds is not None
    start, end, peak = bounds

    # The detected window must bracket the spike burst...
    assert start <= BURST_LO + 5
    assert end >= BURST_HI - 5
    # ...the peak sits inside the burst...
    assert BURST_LO <= peak < BURST_HI
    # ...and it does not run wild into the flat noise on either side.
    assert start >= BURST_LO - 20
    assert end <= BURST_HI + 20


def test_detect_bounds_none_on_pure_noise():
    rng = np.random.default_rng(1)
    signal = rng.uniform(0.0, 15.0, size=N)  # never crosses min_peak=300
    assert injection_extract.detect_injection_bounds(signal) is None


def test_build_result_copy_window_clamped(tmp_path):
    signal = _make_signal()
    start, end, peak = injection_extract.detect_injection_bounds(signal)
    files = [Path(f"frame_{i:06d}.bmp") for i in range(N)]

    result = injection_extract.build_result(
        files, signal, "test", start, end, peak,
        source_dir=tmp_path / "run", dest_base=tmp_path / "dest",
        before=30, after=30, copy=False,
    )

    copy_start = max(0, start - 30)
    copy_end = min(N - 1, end + 30)
    assert result["selected_count"] == copy_end - copy_start + 1
    assert result["injection_count"] == end - start + 1
    assert result["copy_start_frame"] == files[copy_start].name
    assert result["copy_end_frame"] == files[copy_end].name
    assert result["copied"] is False
    # The window stays within the available frames.
    assert 0 <= copy_start <= copy_end <= N - 1


def test_build_result_clamps_at_edges(tmp_path):
    # A burst near the very start: before-padding must clamp at 0, not go negative.
    signal = np.full(N, 5.0)
    signal[0:20] = 3000.0
    start, end, peak = injection_extract.detect_injection_bounds(signal)
    files = [Path(f"frame_{i:06d}.bmp") for i in range(N)]

    result = injection_extract.build_result(
        files, signal, "test", start, end, peak,
        source_dir=tmp_path / "run", dest_base=tmp_path / "dest",
        before=30, after=30, copy=False,
    )
    assert result["copy_start_frame"] == files[0].name
    assert result["selected_count"] >= 1


def test_scan_with_cpp_returns_none_on_garbled_stdout(monkeypatch, tmp_path):
    """F2: a byte count that is not a multiple of 4 must fall through to None
    (so the Python back-ends run) instead of raising out of scan_with_cpp."""
    if not injection_extract.CPP_EXE.exists():
        pytest.skip("scanner exe not present")

    class FakeProc:
        returncode = 0
        stdout = b"\x01\x02\x03\x04\x05"  # 5 bytes -> not a multiple of 4

    monkeypatch.setattr(
        injection_extract.subprocess, "run", lambda *a, **k: FakeProc()
    )
    assert injection_extract.scan_with_cpp(tmp_path, 3) is None
