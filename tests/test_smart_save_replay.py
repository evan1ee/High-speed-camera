"""Replay on a disk burst must select the same window extract_injection copies."""
import cv2
import numpy as np

from hsc import injection_extract, smart_save


def _write_burst(folder, n=60, onset=20, end=45, w=160, h=120):
    folder.mkdir(parents=True)
    scene = np.full((h, w), 15, np.uint8)
    jet = scene.copy()
    jet[55:65, 20:60] = 220
    for i in range(n):
        cv2.imwrite(str(folder / f"frame_{i + 1:06d}.bmp"),
                    jet if onset <= i < end else scene)


def test_replay_matches_extract_injection(tmp_path):
    src = tmp_path / "burst"
    _write_burst(src)
    rep = smart_save.replay(src, before=5, after=7)
    assert rep["bounds"] is not None
    legacy = injection_extract.extract_injection(
        src, dest_base=tmp_path / "inj", before=5, after=7, copy=True)
    copied = sorted(p.name for p in
                    (tmp_path / "inj").rglob("frame_*.bmp"))
    assert rep["names"] == copied
