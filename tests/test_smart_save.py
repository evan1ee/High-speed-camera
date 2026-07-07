"""smart_save: window planning must match build_result's math exactly."""
import numpy as np
import pytest

from hsc import injection_extract, smart_save


def _synthetic_burst(n=60, onset=20, end=45, w=160, h=120):
    """In-RAM burst: static scene, a ~400 px jet appears at `onset` and
    vanishes at `end`. Returns (full_res_frames, signal, small_frames)."""
    ds = injection_extract.DOWNSAMPLE
    scene = np.full((h, w), 15, np.int16)
    jet = scene.copy()
    jet[55:65, 20:60] = 220                     # 40x10 = 400 px > min_peak 300
    frames = [jet if onset <= i < end else scene for i in range(n)]
    signal = np.zeros(n)
    for i in range(1, n):
        signal[i] = float(np.count_nonzero(
            np.abs(frames[i] - frames[i - 1]) > injection_extract.DIFF_THRESH))
    small = [f[::ds, ::ds].astype(np.int16) for f in frames]
    return frames, signal, small


def test_plan_window_finds_the_event_and_clamps():
    _, signal, small = _synthetic_burst()
    bounds, window = smart_save.plan_window(
        signal, lambda i: small[i], len(small), before=30, after=30)
    assert bounds is not None
    start, end, peak = bounds
    assert 18 <= start <= 21          # onset at 20 (+-gap tolerance)
    assert window[0] == max(0, start - 30)          # clamped at 0 here
    assert window[1] == min(len(small) - 1, end + 30)


def test_plan_window_none_when_no_injection():
    n = 40
    signal = np.zeros(n)
    small = [np.zeros((30, 40), np.int16)] * n
    bounds, window = smart_save.plan_window(signal, lambda i: small[i], n, 30, 30)
    assert bounds is None and window is None


def test_window_math_equals_build_result(tmp_path):
    """The one invariant that matters: smart_save selects the SAME files that
    build_result would copy, and make_result mirrors its dict exactly."""
    _, signal, small = _synthetic_burst()
    n = len(small)
    names = [f"frame_{i + 1:06d}.bmp" for i in range(n)]
    fake_files = [tmp_path / nm for nm in names]
    bounds, window = smart_save.plan_window(
        signal, lambda i: small[i], n, before=5, after=7)
    start, end, peak = bounds
    ref = injection_extract.build_result(
        fake_files, signal, "m", start, end, peak,
        source_dir=tmp_path / "run", dest_base=tmp_path / "inj",
        before=5, after=7, copy=False)
    assert window == (max(0, start - 5), min(n - 1, end + 7))
    assert ref["copy_start_frame"] == names[window[0]]
    assert ref["copy_end_frame"] == names[window[1]]
    ours = smart_save.make_result(
        names, signal, bounds, window,
        source_dir=str(tmp_path / "run"), dest_dir=ref["dest_dir"],
        before=5, after=7, method="m")
    # ref was built with copy=False so its "copied" is False; smart save's
    # result always reports copied=True (it wrote the frames itself).
    assert ours == {**ref, "copied": True}


def test_make_meta_matches_edge_v2_schema():
    meta = smart_save.make_meta((20, 45, 21), (15, 52), "in-memory (smart save)")
    assert meta == {"pre_frames": 5, "onset_index": 20, "copy_start": 15,
                    "copy_end": 52, "method": "in-memory (smart save)"}
