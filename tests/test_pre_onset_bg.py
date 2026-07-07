"""Pre-onset background: built only from the jet-free frames at folder start."""
import json

import cv2
import numpy as np
import pytest

from benchmark.synthetic import make_sequence
from hsc import measure_angle as ma


def _write_frames(frames, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        cv2.imwrite(str(folder / f"frame_{i:06d}.bmp"), f)


def test_build_result_writes_meta(tmp_path):
    from hsc import injection_extract as ie
    frames, _ = make_sequence(n_pre=6, n_jet=6, seed=0)
    src = tmp_path / "burst"
    _write_frames(frames, src)
    files = ie.list_frames(src)
    signal = np.zeros(len(files))
    res = ie.build_result(files, signal, "test", start=6, end=11, peak=8,
                          source_dir=src, dest_base=tmp_path / "inj",
                          before=4, after=0, copy=True)
    meta_path = next((tmp_path / "inj").rglob("injection_meta.json"))
    meta = json.loads(meta_path.read_text())
    assert meta["pre_frames"] == 4          # start(6) - copy_start(2)
    assert meta["onset_index"] == 6
    assert meta["copy_start"] == 2


def test_pre_onset_bg_excludes_the_jet(tmp_path):
    frames, truth = make_sequence(n_pre=10, n_jet=10, residual_level=60, seed=0)
    src = tmp_path / "inj"
    _write_frames(frames, src)
    (src / "injection_meta.json").write_text(json.dumps(
        {"pre_frames": 10, "onset_index": 10, "copy_start": 0,
         "copy_end": 19, "method": "test"}))
    files = ma.list_frames(src)
    bg = ma._pre_onset_background(files, src)
    assert bg is not None
    # Background must NOT contain the jet: at jet mid-height it stays at the
    # residual-streak level, far below the jet brightness.
    x = int((truth["x_lo"] + truth["x_hi"]) / 2)
    y = int(round((truth["k_up"] * x + truth["b_up"]
                   + truth["k_lo"] * x + truth["b_lo"]) / 2))
    assert bg[y, x] < 100


def test_pre_onset_bg_falls_back_without_enough_frames(tmp_path):
    frames, _ = make_sequence(n_pre=3, n_jet=8, seed=0)   # 3 < BG_MIN_PRE_FRAMES
    src = tmp_path / "inj"
    _write_frames(frames, src)
    (src / "injection_meta.json").write_text(json.dumps(
        {"pre_frames": 3, "onset_index": 3, "copy_start": 0,
         "copy_end": 10, "method": "test"}))
    assert ma._pre_onset_background(ma.list_frames(src), src) is None
