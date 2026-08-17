#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The real camera, via the IMV SDK.

EXCLUDED FROM COVERAGE -- it cannot run without hardware. In exchange it holds
NO logic: no branching, no computation, only delegation. A test parses this
file and fails if that stops being true, so anything that could be wrong is
somewhere it can be tested.

That includes what a grab's STATUS means. ``grab`` returns the SDK's status
and an unevaluated frame builder (:class:`hsc.hardware.device.Grab`) and
decides nothing; ``hsc/rig/worker.py`` reads it. An earlier version made the
decision here through a dict lookup -- invisible to the AST guard, and it
flattened every non-OK status, a real SDK fault as much as a timeout, into
``None``, which the worker files as a truncated burst.

Error contract: SDK failures surface as plain ``RuntimeError`` (raised by
``capture_image.check``), NOT ``hsc.hardware.device.CameraError`` --
``FakeCamera`` raises ``CameraError`` directly, so the two ``CameraDevice``
implementations disagree here. This adapter cannot reconcile that itself (no
``try`` is permitted, by the same no-logic rule); the rig layer must catch
``RuntimeError`` at the boundary and re-raise as ``CameraError`` so every
caller above has one exception type to catch.
"""

from ctypes import byref, c_void_p, string_at
from functools import partial
from types import SimpleNamespace

import numpy as np

from hsc import capture_image
from hsc.hardware.device import Frame, Grab, sdk_device_index


class ImvCamera:
    """See module docstring. Every method is one SDK call plus a check."""

    def __init__(self):
        self._sdk = capture_image.load_sdk()
        self._cam = None

    def open(self, index):
        self._cam = self._sdk["MvCamera"]()
        capture_image.check(
            self._cam.IMV_CreateHandle(
                self._sdk["IMV_ECreateHandleMode"].modeByIndex,
                byref(c_void_p(sdk_device_index(index)))),
            self._sdk["IMV_OK"], "Create camera handle")
        capture_image.check(self._cam.IMV_Open(), self._sdk["IMV_OK"],
                            "Open camera")

    def configure(self, cfg):
        capture_image.configure_camera(self._cam, self._sdk, SimpleNamespace(
            pixel_format=cfg.pixel_format, width=cfg.width, height=cfg.height,
            center_roi=cfg.center_roi, offset_x=None, offset_y=None,
            exposure_us=cfg.exposure_us, frame_rate=cfg.frame_rate))

    def start(self):
        capture_image.check(self._cam.IMV_StartGrabbing(),
                            self._sdk["IMV_OK"], "Start grabbing")

    def grab(self, timeout_ms):
        """The SDK's status and an unevaluated frame builder -- see
        :class:`hsc.hardware.device.Grab`. What a non-OK status means is
        decided in ``hsc/rig/worker.py``, where it is covered by tests."""
        raw = self._sdk["IMV_Frame"]()
        return Grab(self._cam.IMV_GetFrame(raw, timeout_ms),
                    self._sdk["IMV_OK"], partial(_to_frame, self._sdk, raw))

    def clone(self, frame):
        raw = self._sdk["IMV_Frame"]()
        capture_image.check(self._cam.IMV_CloneFrame(frame.handle, raw),
                            self._sdk["IMV_OK"], "Clone frame")
        return _to_frame(self._sdk, raw)

    def release(self, frame):
        self._cam.IMV_ReleaseFrame(frame.handle)

    def save(self, frame, path):
        capture_image.save_frame(self._cam, frame.handle, path, self._sdk)

    def stop(self):
        self._cam.IMV_StopGrabbing()

    def close(self):
        self._cam.IMV_Close()
        self._cam.IMV_DestroyHandle()


def _to_frame(sdk, raw):
    info = raw.frameInfo
    return _ImvFrame(
        width=info.width, height=info.height, block_id=info.blockId,
        timestamp=info.timeStamp, handle=raw,
        pixels=np.frombuffer(
            string_at(raw.pData, info.size),
            dtype=np.uint8).reshape(info.height, info.width))


class _ImvFrame(Frame):
    """A Frame that also carries the SDK handle for release/clone/save."""

    def __init__(self, width, height, block_id, timestamp, pixels, handle):
        object.__setattr__(self, "handle", handle)
        super().__init__(width, height, block_id, timestamp, pixels)
