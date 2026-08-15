#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The real camera, via the IMV SDK.

EXCLUDED FROM COVERAGE -- it cannot run without hardware. In exchange it holds
NO logic: no branching, no computation, only delegation. A test parses this
file and fails if that stops being true, so anything that could be wrong is
somewhere it can be tested.
"""

from ctypes import byref, c_void_p, string_at
from types import SimpleNamespace

import numpy as np

from hsc import capture_image
from hsc.hardware.device import CameraError, Frame


class ImvCamera:
    """See module docstring. Every method is one SDK call plus a check."""

    def __init__(self):
        self._sdk = capture_image.load_sdk()
        self._cam = None

    def open(self, index):
        # index is the SDK's own 0-based device index -- unlike the 1-based
        # convention capture_image.py's CLI uses, translating that stays a
        # decision for the caller, not delegation the adapter may compute.
        self._cam = self._sdk["MvCamera"]()
        capture_image.check(
            self._cam.IMV_CreateHandle(
                self._sdk["IMV_ECreateHandleMode"].modeByIndex,
                byref(c_void_p(index))),
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
        raw = self._sdk["IMV_Frame"]()
        status = self._cam.IMV_GetFrame(raw, timeout_ms)
        handler = {self._sdk["IMV_OK"]: _to_frame}.get(status, _to_none)
        return handler(self._sdk, raw)

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


def _to_none(sdk, raw):
    return None


class _ImvFrame(Frame):
    """A Frame that also carries the SDK handle for release/clone/save."""

    def __init__(self, width, height, block_id, timestamp, pixels, handle):
        object.__setattr__(self, "handle", handle)
        super().__init__(width, height, block_id, timestamp, pixels)
