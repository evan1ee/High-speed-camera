"""Characterization test: the measurement pipeline must survive the restructure.

A synthetic bright wedge (nozzle on the RIGHT, per NOZZLE_SIDE) with a 10-degree
full opening angle must measure to a sane angle. Tolerance is deliberately wide;
this guards against import/path breakage, not measurement accuracy.
"""
import cv2
import numpy as np


def make_wedge(width=320, height=240, half_angle_deg=5.0):
    img = np.full((height, width), 15, np.uint8)
    apex = (300, 120)
    length = 280
    half = np.tan(np.radians(half_angle_deg)) * length
    pts = np.array(
        [apex,
         (apex[0] - length, int(round(120 - half))),
         (apex[0] - length, int(round(120 + half)))],
        np.int32,
    )
    cv2.fillConvexPoly(img, pts, 230)
    return cv2.GaussianBlur(img, (5, 5), 0)


def test_measure_frame_synthetic_wedge():
    import measure_angle

    result = measure_angle.measure_frame(make_wedge())
    assert result is not None
    assert 3.0 <= result["angle"] <= 18.0
