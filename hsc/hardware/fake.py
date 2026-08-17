#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""A camera that replays a saved burst.

Every test above the hardware seam runs against this, on REAL rig pixels --
the same data that exposed the collar, the illumination falloff and the small
dose drift. That matters more than it sounds: a synthetic gradient would have
passed detectors that the actual frames break.

It can also misbehave on purpose, because the rig's failures are what need
covering: dropped frames (a ``block_id`` gap), and a camera streaming a
different ROI than was programmed.
"""

import shutil
from pathlib import Path

from hsc import injection_extract
from hsc.hardware.device import CameraError, CaptureConfig, Frame, Grab
from hsc.measure_angle import load_gray

#: Nanoseconds, matching the SDK ticks the rig records (measured 2026-08-07:
#: 954320 ticks between frames at 1047.9 fps).
TICKS_PER_SECOND = 1_000_000_000

#: Stand-ins for the vendor's status codes. Nothing above the seam reads the
#: VALUE -- ``Grab.ok`` only compares it with the ok status the same grab
#: carries -- so any distinct pair replays the contract faithfully.
OK_STATUS = 0
#: The burst is over: the replay ran out of frames, as the camera does when it
#: stops delivering. ``fail_status`` replaces it with a fault code, because a
#: real SDK reports both through the same integer.
NO_FRAME_STATUS = -3


class FakeCamera:
    """Replays *source_dir* frame by frame. See module docstring."""

    def __init__(self, source_dir, fps=1738.7, drop_after=None,
                 roi_override=None, fail_status=NO_FRAME_STATUS):
        self._source = Path(source_dir)
        self._fps = float(fps)
        self._drop_after = drop_after
        self._roi_override = roi_override
        self._fail_status = fail_status
        self._files = []
        self._index = 0
        self._block = 0
        self._grabbing = False
        self._open = False
        self._sources = {}
        self.configs = []
        self.saved = []

    # -- lifecycle ---------------------------------------------------------
    def open(self, index):
        self._files = injection_extract.list_frames(self._source)
        if not self._files:
            raise CameraError(f"no frames to replay in {self._source}")
        self._open = True

    def configure(self, cfg):
        if not isinstance(cfg, CaptureConfig):
            raise CameraError("configure needs a CaptureConfig")
        self.configs.append(cfg)

    def start(self):
        self._grabbing = True

    def stop(self):
        self._grabbing = False

    def close(self):
        self._grabbing = False
        self._open = False

    # -- frames ------------------------------------------------------------
    def grab(self, timeout_ms):
        """A ``Grab``, not a frame: the status is the rig layer's to read."""
        if not self._grabbing:
            raise CameraError("camera is not grabbing")
        if self._index >= len(self._files):
            return Grab(self._fail_status, OK_STATUS)
        path = self._files[self._index]
        self._index += 1
        self._block += 1
        if self._drop_after is not None and self._block == self._drop_after + 1:
            self._block += 1                     # the gap a dropped frame leaves
        pixels = load_gray(path)
        height, width = pixels.shape
        if self._roi_override is not None:
            width, height = self._roi_override
        ticks = int(round((self._block - 1) * TICKS_PER_SECOND / self._fps))
        frame = Frame(width=width, height=height, block_id=self._block,
                      timestamp=ticks, pixels=pixels)
        self._sources[id(frame)] = path
        return Grab(OK_STATUS, OK_STATUS, lambda: frame)

    def clone(self, frame):
        clone = Frame(frame.width, frame.height, frame.block_id,
                      frame.timestamp, frame.pixels.copy())
        self._sources[id(clone)] = self._sources[id(frame)]
        return clone

    def release(self, frame):
        self._sources.pop(id(frame), None)

    def save(self, frame, path):
        source = self._sources.get(id(frame))
        if source is None:
            raise CameraError("frame was released before saving")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        self.saved.append(Path(path))
