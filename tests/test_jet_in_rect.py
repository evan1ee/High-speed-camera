"""Per-frame OK/NG verdict: both green jet edge lines inside the red rectangle.

The check runs over the rectangle's x-window (lines are straight, so the two
x endpoints suffice) and only when a reference with a rect is set for the
frame size; without one the verdict is empty and the log line is unchanged.
"""
import cv2
import numpy as np

from benchmark import synthetic
from benchmark.synthetic import make_sequence
from hsc import measure_angle as ma


def _result(k_up, y_up, k_lo, y_lo, x=10.0):
    """Minimal fit-result dict: each edge line passes (x, y) with slope k."""
    return {
        "k_upper": k_up, "up0": np.array([x, y_up]),
        "k_lower": k_lo, "lo0": np.array([x, y_lo]),
    }


def test_jet_in_rect_inside():
    r = _result(0.0, 100.0, 0.0, 110.0)
    assert ma.jet_in_rect(r, [20, 90, 80, 120]) is True


def test_jet_in_rect_upper_line_outside():
    r = _result(0.0, 100.0, 0.0, 110.0)
    assert ma.jet_in_rect(r, [20, 105, 80, 120]) is False


def test_jet_in_rect_sloped_line_exits_far_end():
    # Upper edge starts inside at x=20 (y=105) but climbs out by x=80 (y=135).
    r = _result(0.5, 100.0, 0.0, 110.0)
    assert ma.jet_in_rect(r, [20, 90, 80, 120]) is False


def _measure_with_ref(tmp_path, rect):
    frames, truth = make_sequence(n_pre=14, n_jet=10, noise_sigma=6.0, seed=2)
    src = tmp_path / "inj"
    src.mkdir()
    for i, f in enumerate(frames):
        cv2.imwrite(str(src / f"frame_{i:06d}.bmp"), f)
    ax, ay = synthetic.APEX
    ref = {
        "image_size": [synthetic.W, synthetic.H],
        "nozzle_p0": [ax, ay - 40.0], "nozzle_p1": [ax, ay + 40.0],
        "blue_a": [float(synthetic.W - 1), float(ay)], "blue_b": [0.0, float(ay)],
        "rect": rect,
    }
    old = ma.reference_lines.load_reference
    ma.reference_lines.load_reference = lambda: ref
    try:
        return ma.measure_folder(src, dest_base=tmp_path / "m", start=2, end=9,
                                 start_x=truth["x_lo"], end_x=truth["x_hi"])
    finally:
        ma.reference_lines.load_reference = old


def test_measure_folder_reports_ok(tmp_path):
    ax, ay = synthetic.APEX
    # Generous rect over the middle of the jet: both edges inside -> OK.
    rect = [ax - 150.0, ay - 40.0, ax - 50.0, ay + 40.0]
    out = _measure_with_ref(tmp_path, rect)
    verdicts = dict(out["frame_in_rect"])
    assert verdicts and all(v == "OK" for v in verdicts.values())
    csv_text = next((tmp_path / "m").rglob("*_angles.csv")).read_text()
    assert "in_rect" in csv_text.splitlines()[0]
    assert ",OK" in csv_text


def test_measure_folder_reports_ng(tmp_path):
    ax, ay = synthetic.APEX
    # Rect band above the jet: edges fall outside -> NG.
    rect = [ax - 150.0, ay - 80.0, ax - 50.0, ay - 50.0]
    out = _measure_with_ref(tmp_path, rect)
    verdicts = dict(out["frame_in_rect"])
    assert verdicts and all(v == "NG" for v in verdicts.values())
    csv_text = next((tmp_path / "m").rglob("*_angles.csv")).read_text()
    assert ",NG" in csv_text


def test_measure_folder_without_reference_reports_no_verdict(tmp_path):
    """No reference set for the frame size => the verdict column is empty,
    so a caller can tell 'not checked' from 'checked and failed'."""
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
    assert out["frame_in_rect"]
    assert all(v == "" for _name, v in out["frame_in_rect"])
