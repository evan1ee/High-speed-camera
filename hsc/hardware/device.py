#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The boundary between the rig code and the vendor SDK.

Everything above this module is tested against :class:`~hsc.hardware.fake.
FakeCamera`; the only implementation that touches the DLL is
:mod:`hsc.hardware.imv`, which holds no logic and is excluded from coverage.
"""

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

    def open(self, index: int) -> None: ...
    def configure(self, cfg: CaptureConfig) -> None: ...
    def start(self) -> None: ...
    def grab(self, timeout_ms: int) -> Frame | None: ...
    def clone(self, frame: Frame) -> Frame: ...
    def release(self, frame: Frame) -> None: ...
    def save(self, frame: Frame, path: Path) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
