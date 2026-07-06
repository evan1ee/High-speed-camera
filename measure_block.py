#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Measure the angle of a reference "angle block" (a wedge / angle gauge).

Reuses the same edge-finding + RANSAC/Total-Least-Squares line-fitting approach
as the spray-angle measurement, but for a *solid* object in a single still image
(no temporal
background). The block is assumed to be a wedge: two straight edges meeting at a
vertex (apex). The pipeline:

    Gaussian blur -> Otsu threshold -> largest connected component (the block)
    -> orient by PCA & find the apex (narrow vertex) -> per-slice silhouette
    edges -> Savitzky-Golay smoothing -> ROI (drop the vertex tip and far end)
    -> RANSAC outlier rejection + TLS line fit on each edge
    -> angle = |atan(k_upper) - atan(k_lower)|.

Because the block is a solid silhouette, the edge is the mask boundary itself
(sharp), unlike the soft/asymmetric water-jet edge.
"""

import argparse
from math import atan, degrees
from pathlib import Path

import cv2
import numpy as np
from scipy.signal import savgol_filter

import injection_extract
import measure_angle as ma


DEST_FOLDER_NAME = "measure"
BLOCK_SUBDIR = "angle_block"

GAUSS_KSIZE = 5
SAVGOL_WINDOW = 21
SAVGOL_POLY = 3
N_BINS = 60                 # axial bins for edge sampling along the wedge
ROI_TIP_FRAC = 0.12         # drop this fraction near the vertex (tip is rounded)
ROI_END_FRAC = 0.95         # drop the far end (cut/flat back of the block)
RANSAC_RESIDUAL = 2.0       # px inlier tolerance
MIN_AREA_FRAC = 0.003       # block must be at least this fraction of the frame
SUPERSAMPLE = 3
LINE_COLOR = (0, 255, 0)    # green


def _threshold(gray, invert=None):
    """Otsu binary mask of the block. Auto-picks polarity so the object (the
    minority class) is foreground, unless *invert* is given explicitly."""
    blur = cv2.GaussianBlur(gray, (GAUSS_KSIZE, GAUSS_KSIZE), 0)
    _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if invert is None:
        invert = mask.mean() > 127.5      # foreground is majority -> flip
    if invert:
        mask = cv2.bitwise_not(mask)
    return mask


def measure_block(gray, invert=None, n_bins=N_BINS, line_frac=None):
    """Measure the angle between the two long straight edges of the block.

    Works for a bar / shallow wedge: the block's silhouette has two dominant
    straight edges. We orient by PCA, take the perpendicular extreme on each
    side per axial slice, fit each edge with RANSAC (which rejects background
    that merges into the block at the frame corners), and report the angle
    between the two fitted lines. The lines are drawn across the full length of
    the block.
    """
    mask = _threshold(gray, invert)
    comp, area = ma.largest_component(mask)
    if comp is None or area < MIN_AREA_FRAC * gray.size:
        raise RuntimeError("No angle block found (largest region too small).")

    ys, xs = np.where(comp)
    # Orient so the block runs left-right; transpose if it runs top-bottom.
    horizontal = (xs.max() - xs.min()) >= (ys.max() - ys.min())
    gg = gray if horizontal else np.ascontiguousarray(gray.T)
    cc = comp if horizontal else np.ascontiguousarray(comp.T)

    # Steepest-gradient edges on the RAW image within the block band (the same
    # visible-edge detector used for the spray jet): the mask boundary dips into
    # a dim fringe, so use the intensity transition instead.
    ex, y_top, y_bot = ma.extract_edges(gg, cc)
    if ex.size < 8:
        raise RuntimeError("Not enough edge samples to fit the block angle.")

    # RANSAC outlier rejection + Total Least Squares fit per edge (rejects
    # background merged into the block at the frame corners). Uses the block's
    # own inlier tolerance (RANSAC_RESIDUAL), not the spray default.
    k_up, b_up, n_up, _, _ = ma.tls_fit(ex, y_top, RANSAC_RESIDUAL)
    k_lo, b_lo, n_lo, _, _ = ma.tls_fit(ex, y_bot, RANSAC_RESIDUAL)
    angle = abs(degrees(atan(k_up) - atan(k_lo)))

    def img_point(u, slope, intercept):
        v = slope * u + intercept
        return np.array([u, v]) if horizontal else np.array([v, u])

    if line_frac is not None:
        # Draw from the image left side out to `line_frac` of the width.
        u0, u1 = 0.0, float(line_frac) * (gg.shape[1] - 1)
    else:
        u0, u1 = float(ex.min()), float(ex.max())
    if abs(k_up - k_lo) > 1e-9:                 # intersection (virtual vertex)
        u_int = (b_lo - b_up) / (k_up - k_lo)
        vertex = img_point(u_int, k_up, b_up)
    else:
        vertex = img_point((u0 + u1) / 2, k_up, b_up)

    return {
        "angle": angle,
        "k_upper": k_up,
        "k_lower": k_lo,
        "n_points": int(n_up + n_lo),
        "apex": vertex,
        "up0": img_point(u0, k_up, b_up),
        "up1": img_point(u1, k_up, b_up),
        "lo0": img_point(u0, k_lo, b_lo),
        "lo1": img_point(u1, k_lo, b_lo),
    }


def _savgol(y, window=SAVGOL_WINDOW, poly=SAVGOL_POLY):
    n = len(y)
    if n < poly + 2:
        return y.astype(float)
    win = min(window, n if n % 2 == 1 else n - 1)
    if win % 2 == 0:
        win -= 1
    if win <= poly:
        return y.astype(float)
    return savgol_filter(y.astype(float), win, poly)


def annotate(gray, result, scale=SUPERSAMPLE):
    """Draw the two green edge lines + the vertex + the angle value."""
    big = cv2.resize(
        gray, (gray.shape[1] * scale, gray.shape[0] * scale),
        interpolation=cv2.INTER_CUBIC,
    )
    img = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
    pt = lambda k: tuple(np.round(result[k] * scale).astype(int))
    cv2.line(img, pt("up0"), pt("up1"), LINE_COLOR, 1, cv2.LINE_AA)
    cv2.line(img, pt("lo0"), pt("lo1"), LINE_COLOR, 1, cv2.LINE_AA)
    vx, vy = pt("apex")
    if 0 <= vx < img.shape[1] and 0 <= vy < img.shape[0]:
        cv2.circle(img, (vx, vy), 3, (0, 165, 255), -1)
    cv2.putText(
        img, f"{result['angle']:.2f} deg", (6 * scale, 16 * scale),
        cv2.FONT_HERSHEY_SIMPLEX, 0.45 * scale, LINE_COLOR, 1, cv2.LINE_AA,
    )
    return img


def measure_block_image(image_path, dest_base=None, invert=None, line_frac=None):
    """Measure a still image of the angle block and save an annotated result."""
    image_path = Path(image_path)
    gray = ma.load_gray(image_path)
    result = measure_block(gray, invert=invert, line_frac=line_frac)

    if dest_base is None:
        dest_base = image_path.resolve().parents[0] / DEST_FOLDER_NAME
    dest_dir = Path(dest_base) / BLOCK_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / (image_path.stem + "_angle.bmp")
    cv2.imwrite(str(out), annotate(gray, result))

    with open(dest_dir / "block_angles.csv", "a", encoding="utf-8") as fh:
        fh.write(f"{image_path.name},{result['angle']:.3f},"
                 f"{result['k_upper']:.5f},{result['k_lower']:.5f},{result['n_points']}\n")
    result["out_path"] = str(out)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="still image of the angle block")
    parser.add_argument("--dest", default=None, help="destination base folder")
    parser.add_argument("--invert", action="store_true", help="force dark-block-on-bright")
    args = parser.parse_args()
    r = measure_block_image(args.image, args.dest, invert=True if args.invert else None)
    print(f"block angle : {r['angle']:.2f} deg")
    print(f"k_upper     : {r['k_upper']:.5f}")
    print(f"k_lower     : {r['k_lower']:.5f}")
    print(f"edge points : {r['n_points']}")
    print(f"saved to    : {r['out_path']}")


if __name__ == "__main__":
    main()
