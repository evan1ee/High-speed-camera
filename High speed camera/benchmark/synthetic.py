"""Synthetic spray frames with exactly known edge lines.

Frames are rendered at 8x supersampling then area-downscaled, so the true
edges land at genuine subpixel positions. Geometry mirrors the rig: nozzle on
the RIGHT, jet travelling left, near-horizontal edges.
"""
import cv2
import numpy as np

W, H, SS = 320, 240, 8
APEX = (300.0, 120.0)          # nozzle tip (x, y) in image coords
JET_LEN = 270.0                # wedge length in px
APEX_HALF_W = 2.0              # half-width of the jet at the apex (px)


def _truth(half_angle_deg):
    """True upper/lower line params for a wedge opening by half_angle each side."""
    k = np.tan(np.radians(half_angle_deg))
    ax, ay = APEX
    # upper edge: y decreases going left from (ax, ay - APEX_HALF_W)
    k_up, b_up = k, (ay - APEX_HALF_W) - k * ax
    k_lo, b_lo = -k, (ay + APEX_HALF_W) + k * ax
    return {"k_up": k_up, "b_up": b_up, "k_lo": k_lo, "b_lo": b_lo,
            "x_lo": ax - JET_LEN, "x_hi": ax - 20.0}


def _render_wedge(half_angle_deg, brightness):
    truth = _truth(half_angle_deg)
    big = np.zeros((H * SS, W * SS), np.float64)
    ax, ay = APEX
    x0 = ax - JET_LEN
    pts = np.array([
        [ax, truth["k_up"] * ax + truth["b_up"]],
        [x0, truth["k_up"] * x0 + truth["b_up"]],
        [x0, truth["k_lo"] * x0 + truth["b_lo"]],
        [ax, truth["k_lo"] * ax + truth["b_lo"]],
    ]) * SS
    cv2.fillConvexPoly(big, np.round(pts).astype(np.int32), float(brightness))
    img = cv2.resize(big, (W, H), interpolation=cv2.INTER_AREA)
    return img, truth


def _apply_skirt(img, skirt_scale):
    """One-sided exponential tail downward: brightens BELOW edges only."""
    if skirt_scale <= 0:
        return img
    n = int(np.ceil(skirt_scale * 4))
    out = img.copy()
    for d in range(1, n + 1):
        shifted = np.zeros_like(img)
        shifted[d:, :] = img[:-d, :]
        out = np.maximum(out, shifted * np.exp(-d / skirt_scale))
    return out


def make_wedge(half_angle_deg=3.0, blur_sigma=1.0, noise_sigma=3.0,
               skirt_scale=0.0, brightness=230, base_level=12, seed=0):
    """One frame + ground-truth lines. Skirt is applied to the LOWER side only
    (physically: reflection/spray fallout below the jet)."""
    img, truth = _render_wedge(half_angle_deg, brightness)
    img = _apply_skirt(img, skirt_scale)
    if blur_sigma > 0:
        img = cv2.GaussianBlur(img, (0, 0), blur_sigma)
    rng = np.random.default_rng(seed)
    img = img + base_level + rng.normal(0.0, noise_sigma, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8), truth


def _static_scene(residual_level, rng):
    """Static background: bright nozzle block on the right + faint horizontal
    residual streak along the jet axis (the background-leak scenario)."""
    scene = np.full((H, W), 12.0)
    scene[100:140, 302:320] = 200.0                       # nozzle/holder
    if residual_level > 0:
        scene[117:124, 60:300] = float(residual_level)    # residual stream
    return cv2.GaussianBlur(scene, (0, 0), 1.0)


def make_sequence(n_pre=12, n_jet=15, half_angle_deg=3.0, blur_sigma=1.0,
                  noise_sigma=3.0, skirt_scale=2.0, brightness=230,
                  residual_level=60, seed=0):
    """n_pre jet-free frames then n_jet steady-jet frames, same static scene."""
    rng = np.random.default_rng(seed)
    scene = _static_scene(residual_level, rng)
    jet, truth = _render_wedge(half_angle_deg, brightness)
    jet = _apply_skirt(jet, skirt_scale)
    frames = []
    for i in range(n_pre + n_jet):
        f = scene + (jet if i >= n_pre else 0.0)
        if blur_sigma > 0:
            f = cv2.GaussianBlur(f, (0, 0), blur_sigma)
        f = f + rng.normal(0.0, noise_sigma, f.shape)
        frames.append(np.clip(f, 0, 255).astype(np.uint8))
    return frames, truth
