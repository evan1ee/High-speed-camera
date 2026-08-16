"""Auto-pick measure mode: find the first run of AUTO_PICK_COUNT consecutive
measurable frames whose jet span is stable, instead of fixed start..end."""
import cv2

from benchmark.synthetic import make_sequence
from hsc import measure_angle as ma


def test_stable_window_skips_growing_burst():
    # Burst grows (unstable), then the jet settles: pick the first stable run.
    spans = [50.0, 120.0, 190.0, 240.0, 270.0,          # growing burst
             284.0, 285.0, 286.0, 284.0, 285.0, 285.0]  # steady
    idx = ma.find_stable_window(spans, count=5, tol=0.05)
    assert idx == 5


def test_stable_window_requires_consecutive_frames():
    # A None (unmeasurable frame) breaks the run.
    spans = [284.0, 285.0, None, 284.0, 285.0, 286.0, 284.0, 285.0]
    idx = ma.find_stable_window(spans, count=5, tol=0.05)
    assert idx == 3


def test_stable_window_none_when_unstable():
    spans = [100.0, 200.0, 100.0, 200.0, 100.0, 200.0]
    assert ma.find_stable_window(spans, count=5, tol=0.05) is None


def test_stable_window_rejects_unstable_angle():
    # A fast jet reaches full span immediately, so the burst frames have a
    # stable SPAN but a wildly varying ANGLE -- they must not be picked.
    spans = [285.0] * 10
    angles = [6.2, 3.9, 2.8, 2.2, 1.8,            # burst: angle settling
              1.25, 1.22, 1.24, 1.21, 1.23]       # steady
    idx = ma.find_stable_window(spans, angles=angles, count=5, tol=0.05)
    assert idx == 5


def test_measure_folder_auto_pick_ignores_start_end(tmp_path):
    """``auto_pick=True`` measures the settled jet regardless of start/end.

    The fixed-index path would measure jet frames 40..41 -- frames that do not
    exist in this 10-frame jet -- and find nothing. Auto-pick walks from the
    first measurable jet frame instead, so it still returns a full window.
    """
    n_pre = 14
    frames, truth = make_sequence(n_pre=n_pre, n_jet=12, noise_sigma=3.0,
                                  seed=5)
    src = tmp_path / "inj"
    src.mkdir()
    for i, frame in enumerate(frames):
        cv2.imwrite(str(src / f"frame_{i:06d}.bmp"), frame)

    out = ma.measure_folder(src, dest_base=tmp_path / "m", start=40, end=41,
                            start_x=truth["x_lo"], end_x=truth["x_hi"],
                            auto_pick=True)

    assert out["auto_pick"] is True
    picked = [name for name, _angle in out["frames"]]
    assert len(picked) == ma.AUTO_PICK_COUNT
    # The jet-free padding frames hold no jet, so they can never be picked.
    assert all(int(name[6:12]) >= n_pre for name in picked), picked
