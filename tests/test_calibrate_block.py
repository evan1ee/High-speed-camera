"""Auto-calibration must detect BOTH block polarities.

The 5 mm calibration block images as a bright bar on a dark background (its two
reference edges are bright<->dark steps); the older chamfered block images as a
bright block with two dark edge-lines. ``auto_rois`` must find the two edges in
either case and report the correct fit mode, and the fitted gap must match the
synthetic ground truth.
"""

import numpy as np
import pytest

from hsc import calibrate_scale as cs


def _bright_block(h=240, w=320, top=60, bot=185, bg=20, fg=235):
    """A bright horizontal bar (the 5 mm block): dark background, bright block
    spanning the full width, top edge at ``top`` and bottom edge at ``bot``."""
    img = np.full((h, w), bg, np.float64)
    img[top:bot + 1, :] = fg
    return img


def _dark_line_block(h=240, w=320, r1=60, r2=185, block=220, dark=70):
    """A bright block with two dark horizontal edge-lines at rows r1, r2 (a thin
    dark trough with bright block on both sides) -- the old chamfer look."""
    img = np.full((h, w), block, np.float64)
    for r in (r1, r2):
        img[r - 1:r + 2, :] = dark
    return img


def test_auto_rois_bright_block_uses_step():
    gray = _bright_block(top=60, bot=185)
    roi1, roi2, mode = cs.auto_rois(gray)
    assert mode == "step"
    result = cs.calibrate_from_rois(gray, roi1, roi2, ref_mm=5.0)
    # gap between the two bright-block edges is bot - top = 125 px
    assert result["gap_px"] == pytest.approx(125.0, abs=1.0)
    assert result["mm_per_px"] == pytest.approx(5.0 / 125.0, rel=0.02)


def test_auto_rois_dark_line_block_uses_outer():
    gray = _dark_line_block(r1=60, r2=185)
    roi1, roi2, mode = cs.auto_rois(gray)
    assert mode == "outer"
    result = cs.calibrate_from_rois(gray, roi1, roi2, ref_mm=10.0)
    # outer flanks of the two dark lines are ~1 px outside their centres,
    # so the gap is a touch over the 125 px centre-to-centre spacing.
    assert result["gap_px"] == pytest.approx(127.0, abs=2.0)


def test_calibrate_from_rois_auto_matches_explicit_step():
    gray = _bright_block(top=60, bot=185)
    roi1, roi2, _ = cs.auto_rois(gray)
    auto = cs.calibrate_from_rois(gray, roi1, roi2, ref_mm=5.0, mode="auto")
    step = cs.calibrate_from_rois(gray, roi1, roi2, ref_mm=5.0, mode="step")
    assert auto["gap_px"] == pytest.approx(step["gap_px"], abs=1e-9)


def test_auto_rois_raises_without_two_edges():
    gray = np.full((240, 320), 128, np.float64)      # blank frame, no block
    with pytest.raises(RuntimeError):
        cs.auto_rois(gray)


def test_measure_block_size_uses_stored_scale(tmp_path, monkeypatch):
    """measure_block_size reads mm/px from calibration.json and reports mm
    without rewriting the stored calibration -- for a bright block too."""
    import cv2

    from hsc import app_paths

    root = tmp_path
    monkeypatch.setattr(app_paths, "data_root", lambda: root)
    monkeypatch.setattr(cs, "data_root", lambda: root)
    settings = root / "settings"
    settings.mkdir()
    monkeypatch.setattr(app_paths, "settings_path", lambda name: settings / name)
    monkeypatch.setattr(cs, "settings_path", lambda name: settings / name)

    # Stored scale: 0.04 mm/px (so a 125 px block reads as 5.0 mm).
    (settings / cs.CALIBRATION_FILE).write_text(
        '{"mm_per_px": 0.04, "px_per_mm": 25.0, "ref_mm": 5.0}', encoding="utf-8")

    img_path = tmp_path / "blk.bmp"
    cv2.imwrite(str(img_path), _bright_block(top=60, bot=185).astype(np.uint8))

    out = cs.measure_block_size(img_path, save=False)
    assert out["mm"] == pytest.approx(5.0, abs=0.1)
    assert out["mm_per_px"] == 0.04
