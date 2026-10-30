"""The synthetic wedge generator must produce frames whose true edges are known."""
import numpy as np

from benchmark.synthetic import make_wedge, make_sequence


def test_wedge_edges_are_where_truth_says():
    img, truth = make_wedge(half_angle_deg=3.0, blur_sigma=1.0, noise_sigma=0.0,
                            skirt_scale=0.0, brightness=230, seed=0)
    assert img.shape == (240, 320) and img.dtype == np.uint8
    # At mid-ROI, the column must be bright between the true lines and dark
    # well outside them.
    x = int((truth["x_lo"] + truth["x_hi"]) / 2)
    y_up = truth["k_up"] * x + truth["b_up"]
    y_lo = truth["k_lo"] * x + truth["b_lo"]
    assert y_lo > y_up  # image coords: upper edge has the smaller y
    mid = int(round((y_up + y_lo) / 2))
    assert img[mid, x] > 180
    assert img[int(round(y_up)) - 5, x] < 40
    assert img[int(round(y_lo)) + 5, x] < 40


def test_skirt_only_affects_the_lower_side():
    a, truth = make_wedge(half_angle_deg=3.0, blur_sigma=1.0, noise_sigma=0.0,
                          skirt_scale=0.0, brightness=230, seed=0)
    b, _ = make_wedge(half_angle_deg=3.0, blur_sigma=1.0, noise_sigma=0.0,
                      skirt_scale=3.0, brightness=230, seed=0)
    x = int((truth["x_lo"] + truth["x_hi"]) / 2)
    y_up = int(round(truth["k_up"] * x + truth["b_up"]))
    y_lo = int(round(truth["k_lo"] * x + truth["b_lo"]))
    # Below the lower edge the skirted image is brighter (the tail)...
    assert int(b[y_lo + 3, x]) > int(a[y_lo + 3, x]) + 5
    # ...above the upper edge the two are (nearly) identical.
    assert abs(int(b[y_up - 3, x]) - int(a[y_up - 3, x])) <= 2


def test_sequence_has_jet_free_head():
    frames, truth = make_sequence(n_pre=12, n_jet=15, half_angle_deg=3.0,
                                  residual_level=60, seed=0)
    assert len(frames) == 27
    # Pre-onset frames contain the static scene but no jet.
    x = int((truth["x_lo"] + truth["x_hi"]) / 2)
    y_mid = int(round((truth["k_up"] * x + truth["b_up"]
                       + truth["k_lo"] * x + truth["b_lo"]) / 2))
    assert frames[5][y_mid, x] < 100      # only the faint residual streak
    assert frames[20][y_mid, x] > 180     # jet present
