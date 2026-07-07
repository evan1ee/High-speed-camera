"""Pooled fit across frames must be at least as stable as per-frame angles."""
import cv2
import numpy as np

from benchmark.synthetic import make_sequence
from hsc import measure_angle as ma


def test_pooled_angle_close_to_truth_and_reported(tmp_path):
    # Pre-majority window: the synthetic jet is perfectly static, so a
    # jet-majority window median would contain the jet and erase it.
    frames, truth = make_sequence(n_pre=14, n_jet=10, noise_sigma=6.0, seed=2)
    src = tmp_path / "inj"
    src.mkdir()
    for i, f in enumerate(frames):
        cv2.imwrite(str(src / f"frame_{i:06d}.bmp"), f)
    old = ma.reference_lines.load_reference
    ma.reference_lines.load_reference = lambda: None
    try:
        out = ma.measure_folder(src, dest_base=tmp_path / "m", start=2, end=9,
                                start_x=truth["x_lo"], end_x=truth["x_hi"])
    finally:
        ma.reference_lines.load_reference = old
    true_angle = abs(np.degrees(np.arctan(truth["k_up"]))
                     - np.degrees(np.arctan(truth["k_lo"])))
    assert "pooled_angle" in out and out["pooled_n"] > 0
    assert abs(out["pooled_angle"] - true_angle) <= \
        abs(out["mean_angle"] - true_angle) + 0.15
    csv_text = (tmp_path / "m").rglob("angles.csv").__next__().read_text()
    assert "pooled_angle" in csv_text
