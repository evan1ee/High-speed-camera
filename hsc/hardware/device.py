#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The boundary between the rig code and the vendor SDK.

Everything above this module is tested against :class:`~hsc.hardware.fake.
FakeCamera`; the only implementation that touches the DLL is
:mod:`hsc.hardware.imv`, which holds no logic and is excluded from coverage.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


class CameraError(RuntimeError):
    """The camera or SDK refused an operation."""


class CameraConfigError(CameraError):
    """A capture configuration the sensor cannot honour."""


#: The sensor's ROI increment. A request off this grid is silently rounded by
#: the camera, which would produce a burst of a different size than the
#: calibration it is measured against.
ROI_INCREMENT = 4


def sdk_device_index(index: int) -> int:
    """Translate the rig's 1-based camera index to the SDK's 0-based one.

    The whole application is 1-based -- see capture_image.DEFAULT_CAPTURE_CONFIG
    and its ``1 <= index <= nDevNum`` validation. The SDK is 0-based. Keeping the
    translation here, rather than in the coverage-excluded adapter, is what makes
    it testable.
    """
    if index < 1:
        raise CameraConfigError(
            f"camera index is 1-based and must be >= 1, got {index}")
    return index - 1


@dataclass(frozen=True, eq=False)
class Frame:
    """One grabbed frame.

    ``block_id`` and ``timestamp`` are carried because the entire speed axis
    depends on them: the camera free-runs, ``AcquisitionFrameRate`` reports a
    stale stored value, and gaps in ``block_id`` are the only evidence of a
    dropped frame. ``timestamp`` is in RAW SDK TICKS -- the unit is inferred
    later by ``measure_piston.resolve_timebase``; never convert it here.

    Frames compare by identity (not pixel value); compare pixel data explicitly
    with ``np.array_equal(frame1.pixels, frame2.pixels)``.
    """

    width: int
    height: int
    block_id: int
    timestamp: int
    pixels: np.ndarray

    @property
    def shape(self):
        return (self.height, self.width)


@dataclass(frozen=True)
class Grab:
    """One grab attempt, before anyone has decided what it MEANS.

    The SDK answers with an integer status and a frame struct. Turning that
    status into "a frame" or "nothing" is a decision, and decisions may not
    live in :mod:`hsc.hardware.imv` -- it is excluded from coverage and a test
    holds it to pure delegation. The adapter used to make it anyway, laundered
    through a dict lookup that the AST guard could not see, and the cost was
    real: EVERY non-OK status, a genuine SDK fault as much as a timeout, became
    ``None``, which the worker reads as a truncated burst. An SDK error
    mid-stroke was therefore filed as a short stroke, in the one file no test
    covers. So the adapter hands back both halves and the rig layer decides,
    where that can be tested.

    ``ok_status`` travels with the status so the rig layer never needs the
    vendor's own constant; ``build`` is deferred and is ``None`` unless the
    grab succeeded, because a failed grab leaves the frame struct without a
    valid buffer and reading it would take the process down with it.
    """

    status: int
    ok_status: int
    build: Callable[[], "Frame"] | None = None

    @property
    def ok(self):
        return self.status == self.ok_status


@dataclass(frozen=True)
class CaptureConfig:
    """What to program onto the camera before grabbing."""

    width: int
    height: int
    exposure_us: float
    pixel_format: str = "Mono8"
    center_roi: bool = True
    frame_rate: float | None = None      # None: free-run at the sensor maximum

    def __post_init__(self):
        for name in ("width", "height"):
            value = getattr(self, name)
            if value <= 0 or value % ROI_INCREMENT:
                raise CameraConfigError(
                    f"{name} must be a positive multiple of {ROI_INCREMENT}, "
                    f"got {value}")
        if self.exposure_us <= 0:
            raise CameraConfigError(
                f"exposure must be positive, got {self.exposure_us}")


@runtime_checkable
class CameraDevice(Protocol):
    """The camera operations the rig needs. See fake.py for the reference."""

    def open(self, index: int) -> None:
        """Open the ``index``-th camera. ``index`` is 1-based, matching the
        rig's own convention (``capture_image.DEFAULT_CAPTURE_CONFIG``) --
        NOT the SDK's 0-based one. See ``sdk_device_index``."""
        ...
    def configure(self, cfg: CaptureConfig) -> None: ...
    def start(self) -> None: ...
    def grab(self, timeout_ms: int) -> Grab:
        """The SDK's raw answer, NOT a frame. See :class:`Grab`: what a non-OK
        status means is the rig layer's decision, because that is where it can
        be tested."""
        ...
    def clone(self, frame: Frame) -> Frame: ...
    def release(self, frame: Frame) -> None: ...
    def save(self, frame: Frame, path: Path) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
