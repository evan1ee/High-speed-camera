"""Score a measure_frame result against synthetic ground truth."""
from math import atan, degrees

import numpy as np


def _line_of(result, which):
    """(k, b) of the fitted upper/lower line from the result's endpoints."""
    p0, p1 = result[f"{which}0"], result[f"{which}1"]
    k = (p1[1] - p0[1]) / (p1[0] - p0[0])
    return float(k), float(p0[1] - k * p0[0])


def score_frame(result, truth):
    """Per-edge |angle error| (deg) and mean perpendicular distance (px)
    sampled over the truth ROI columns."""
    xs = np.linspace(truth["x_lo"], truth["x_hi"], 50)
    out = {}
    for which, kt, bt in (("up", truth["k_up"], truth["b_up"]),
                          ("lo", truth["k_lo"], truth["b_lo"])):
        kf, bf = _line_of(result, which)
        out[f"ang_err_{which}"] = abs(degrees(atan(kf)) - degrees(atan(kt)))
        d = np.abs((kf * xs + bf) - (kt * xs + bt)) / np.sqrt(1.0 + kf * kf)
        out[f"dist_{which}"] = float(d.mean())
    return out
