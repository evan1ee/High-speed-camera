"""The end rule for an injection that permanently changes the scene.

A water jet in air clears: presence inside the jet mask falls back toward the
pre-onset background, and ``detect_bounds_with_presence`` calls the end where
it settles. A jet fired INTO a gel block does not clear -- the gel stays
deformed and dyed, so presence never returns and the presence rule has no
trough that means "jet gone".

Frame-to-frame motion DOES stop when the gel stops moving, so the temporal
rule still finds the real end. These tests pin both halves: that the presence
rule is wrong on this scene, and that ``end_rule="temporal"`` is right.
"""
import numpy as np
import pytest

from hsc import injection_extract


N = 300
ONSET = 80         # motion starts
SETTLE = 105       # gel stops moving; the scene stays changed forever after
H, W = 100, 200    # downsampled frame size
GROWTH = 8         # columns the dyed region gains per frame while moving


def _frames_and_signal():
    """A scene that changes during [ONSET, SETTLE) and then stays changed.

    The dyed region sweeps across the frame while the jet is moving, then
    holds its final size -- so frame-to-frame motion returns to zero while
    every later frame still differs enormously from the pre-onset background.
    """
    frames = np.full((N, H, W), 10, dtype=np.int16)
    signal = np.zeros(N, dtype=np.float64)

    final = min(W, GROWTH * (SETTLE - ONSET))
    for i in range(N):
        if i < ONSET:
            grown = 0
        elif i < SETTLE:
            grown = min(final, GROWTH * (i - ONSET + 1))
        else:
            grown = final
        if grown:
            frames[i, :, :grown] = 200

    # Temporal signal = changed pixels between consecutive frames, the same
    # quantity compute_motion_signal produces. Comfortably above min_peak
    # while the region grows, exactly zero once it stops.
    for i in range(1, N):
        signal[i] = np.count_nonzero(np.abs(frames[i] - frames[i - 1]) > 25)
    return frames, signal


def _getter(frames):
    return lambda i: frames[i]


def test_the_scene_really_does_stay_changed():
    """Guard the fixture itself: motion stops, difference-from-background does not."""
    frames, signal = _frames_and_signal()
    bg = frames[0]

    assert signal[SETTLE + 20] == 0, "motion must stop once the gel is at rest"
    late_presence = np.count_nonzero(np.abs(frames[-1] - bg) > 25)
    assert late_presence > 100, "the scene must still differ from background at the end"


def test_temporal_end_rule_finds_the_moment_motion_stops():
    frames, signal = _frames_and_signal()
    bounds = injection_extract.detect_bounds_with_presence(
        signal, _getter(frames), N, end_rule="temporal",
    )
    assert bounds is not None
    start, end, peak = bounds

    assert start <= ONSET + 5, f"onset should be near {ONSET}, got {start}"
    assert SETTLE - 15 <= end <= SETTLE + 15, (
        f"end should be near {SETTLE} (motion stops), got {end}"
    )


def test_presence_end_rule_is_wrong_on_a_scene_that_stays_changed():
    """Why the gel path needs its own rule -- not a bug report, a boundary."""
    frames, signal = _frames_and_signal()
    bounds = injection_extract.detect_bounds_with_presence(
        signal, _getter(frames), N,
    )
    assert bounds is not None
    _, presence_end, _ = bounds

    temporal_end = injection_extract.detect_bounds_with_presence(
        signal, _getter(frames), N, end_rule="temporal",
    )[1]
    assert presence_end != temporal_end, (
        "if these ever agree the presence rule has learned to handle a "
        "permanently-changed scene, and the gel path no longer needs a flag"
    )


def test_the_default_is_still_the_presence_rule():
    """Spray and monitor must be untouched by adding the parameter."""
    import inspect
    sig = inspect.signature(injection_extract.detect_bounds_with_presence)
    assert sig.parameters["end_rule"].default == "presence"


def test_an_unknown_end_rule_is_refused():
    frames, signal = _frames_and_signal()
    with pytest.raises(ValueError, match="end_rule"):
        injection_extract.detect_bounds_with_presence(
            signal, _getter(frames), N, end_rule="whatever",
        )
