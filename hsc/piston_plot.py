#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Minimal XY line plots drawn with OpenCV.

The piston measurement needs distance-time and speed-time curves next to its
CSV. Plotting them with the OpenCV that is already a dependency keeps the
frozen one-folder build lean (matplotlib would add tens of MB), at the cost of
plain-looking axes. Pure NumPy/OpenCV, no display needed.
"""

from math import floor, log10

import cv2
import numpy as np


WIDTH, HEIGHT = 760, 440
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 84, 24, 44, 62
BG = (255, 255, 255)
AXIS = (60, 60, 60)
GRID = (222, 222, 222)
TEXT = (40, 40, 40)
CURVE = (0, 150, 0)                 # BGR: green, matching the measured lines
FONT = cv2.FONT_HERSHEY_SIMPLEX
N_TICKS = 5


def _nice_step(span, target=N_TICKS):
    """A 1/2/5 x 10^k step that puts about *target* ticks across *span*."""
    if not np.isfinite(span) or span <= 0:
        return 1.0
    raw = span / max(1, target)
    magnitude = 10.0 ** floor(log10(raw))
    for multiple in (1.0, 2.0, 5.0):
        if raw <= multiple * magnitude:
            return multiple * magnitude
    return 10.0 * magnitude


def _fmt(value, step):
    decimals = 0 if step >= 1 else min(4, int(-floor(log10(step))) + 1)
    text = f"{value:.{decimals}f}"
    return text[1:] if text.startswith("-") and float(text) == 0.0 else text


def _ticks(lo, hi):
    step = _nice_step(hi - lo)
    first = np.ceil(lo / step) * step
    values = np.arange(first, hi + 0.5 * step, step)
    return [v for v in values if lo - 1e-9 <= v <= hi + 1e-9], step


def _limits(values):
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = float(finite.min()), float(finite.max())
    if hi - lo < 1e-12:
        pad = max(abs(hi) * 0.05, 0.5)
        return lo - pad, hi + pad
    pad = 0.05 * (hi - lo)
    return lo - pad, hi + pad


def line_plot(x, y, title="", x_label="", y_label="", width=WIDTH,
              height=HEIGHT, color=CURVE, mark_x=None):
    """Render ``y`` against ``x`` as a BGR image.

    NaN gaps in *y* break the curve rather than jumping across them.
    *mark_x* draws a vertical guide (used for the stroke start at t=0).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    img = np.full((height, width, 3), BG, dtype=np.uint8)

    x_lo, x_hi = _limits(x)
    y_lo, y_hi = _limits(y)
    plot_w = width - MARGIN_L - MARGIN_R
    plot_h = height - MARGIN_T - MARGIN_B

    def to_px(xv, yv):
        px = MARGIN_L + (xv - x_lo) / (x_hi - x_lo) * plot_w
        py = MARGIN_T + (1.0 - (yv - y_lo) / (y_hi - y_lo)) * plot_h
        return int(round(px)), int(round(py))

    x_ticks, x_step = _ticks(x_lo, x_hi)
    y_ticks, y_step = _ticks(y_lo, y_hi)

    for tick in x_ticks:
        px, _ = to_px(tick, y_lo)
        cv2.line(img, (px, MARGIN_T), (px, MARGIN_T + plot_h), GRID, 1)
        label = _fmt(tick, x_step)
        (tw, _), _ = cv2.getTextSize(label, FONT, 0.42, 1)
        cv2.putText(img, label, (px - tw // 2, MARGIN_T + plot_h + 20),
                    FONT, 0.42, TEXT, 1, cv2.LINE_AA)
    for tick in y_ticks:
        _, py = to_px(x_lo, tick)
        cv2.line(img, (MARGIN_L, py), (MARGIN_L + plot_w, py), GRID, 1)
        label = _fmt(tick, y_step)
        (tw, th), _ = cv2.getTextSize(label, FONT, 0.42, 1)
        cv2.putText(img, label, (MARGIN_L - tw - 8, py + th // 2),
                    FONT, 0.42, TEXT, 1, cv2.LINE_AA)

    if mark_x is not None and x_lo <= mark_x <= x_hi:
        px, _ = to_px(mark_x, y_lo)
        cv2.line(img, (px, MARGIN_T), (px, MARGIN_T + plot_h), (170, 170, 255), 1)

    # Axes on top of the grid.
    cv2.rectangle(img, (MARGIN_L, MARGIN_T),
                  (MARGIN_L + plot_w, MARGIN_T + plot_h), AXIS, 1)

    # Curve, split at NaN gaps.
    valid = np.isfinite(x) & np.isfinite(y)
    segment = []
    for i in range(x.size):
        if valid[i]:
            segment.append(to_px(x[i], y[i]))
            continue
        if len(segment) > 1:
            cv2.polylines(img, [np.array(segment, dtype=np.int32)], False,
                          color, 2, cv2.LINE_AA)
        segment = []
    if len(segment) > 1:
        cv2.polylines(img, [np.array(segment, dtype=np.int32)], False,
                      color, 2, cv2.LINE_AA)

    if title:
        cv2.putText(img, title, (MARGIN_L, 28), FONT, 0.6, TEXT, 1, cv2.LINE_AA)
    if x_label:
        (tw, _), _ = cv2.getTextSize(x_label, FONT, 0.48, 1)
        cv2.putText(img, x_label, (MARGIN_L + (plot_w - tw) // 2, height - 16),
                    FONT, 0.48, TEXT, 1, cv2.LINE_AA)
    if y_label:
        # Rotate the y label so it reads bottom-up along the axis.
        (tw, th), _ = cv2.getTextSize(y_label, FONT, 0.48, 1)
        strip = np.full((th + 8, tw + 8, 3), BG, dtype=np.uint8)
        cv2.putText(strip, y_label, (4, th + 2), FONT, 0.48, TEXT, 1, cv2.LINE_AA)
        strip = cv2.rotate(strip, cv2.ROTATE_90_COUNTERCLOCKWISE)
        sh, sw = strip.shape[:2]
        top = MARGIN_T + max(0, (plot_h - sh) // 2)
        if top + sh <= height and sw <= MARGIN_L:
            img[top : top + sh, 2 : 2 + sw] = strip
    return img


def save_line_plot(path, x, y, **kwargs):
    cv2.imwrite(str(path), line_plot(x, y, **kwargs))
    return str(path)
