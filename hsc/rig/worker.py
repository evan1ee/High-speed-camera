#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The single camera thread's work, independent of any UI.

Ported from ``hsc/gui/camera_worker.py``. Three behaviours here were each
learned from a failed rig run and are now covered for the first time:

* the camera is REPROGRAMMED before the burst -- otherwise it keeps the frame
  period of whatever the preview last set, and run 2026-08-13-09-18-35
  delivered correctly-shaped 320x64 frames at the 320x120 period (1798 fps
  instead of 2624), which the size check cannot catch;
* every frame's size is verified, because mm/px is calibrated at one ROI and a
  burst at another would be measured against the wrong magnification;
* every frame's ``block_id`` and ``timestamp`` are recorded, because frame
  index is not time when the camera free-runs, and gaps are the only evidence
  of a dropped frame.

Timestamps are stored as RAW TICKS relative to the first frame. The unit is
inferred later by ``measure_piston.resolve_timebase``; converting here would
throw away the evidence it uses.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from hsc import capture_image, injection_extract, piston_track
from hsc.hardware.device import CameraError


class WrongFrameSize(RuntimeError):
    """The camera streamed a size other than the one programmed."""


@dataclass(frozen=True)
class BurstResult:
    output_dir: Path
    frames: int
    fps: float
    dropped: int
    elapsed_s: float
    #: The camera stopped delivering before the requested duration was up. A
    #: truncated burst is NOT self-evident downstream: ``elapsed_s`` is
    #: measured to the break, so ``fps`` still reads ~1048 and
    #: ``detect_piston_bounds`` scales its trigger off the travel it can see,
    #: happily reporting a shortened stroke and a plausible, quietly low peak
    #: speed. This flag is the only warning anyone gets.
    truncated: bool


class CameraWorker:
    def __init__(self, device, bus, burst_dir):
        self._device = device
        self._bus = bus
        self._burst_dir = Path(burst_dir)
        self._opened = False

    def capture_piston(self, cfg, duration_s, label="", prefix="frame",
                       ext=".bmp", cancel=None):
        """Fixed-length burst for a piston run: keep EVERY frame and record
        each one's block id + timestamp.

        Deliberately its own loop rather than a flag on the spray capture: the
        spray path's detect-before-write branch keys off the *jet's* motion
        signal, which says nothing about the piston, and keeping the two apart
        means the tuned spray pipeline cannot regress when this one changes.
        """
        # Open ONCE for the worker's lifetime, as the Tk camera thread did.
        # ImvCamera.open builds a new handle and calls IMV_Open every time
        # without closing the previous one, so opening per burst would leak the
        # first handle and let the SDK refuse the second burst -- and this
        # process is long-lived now, serving run after run.
        #
        # The camera index is 1-BASED throughout the rig; the SDK's 0-based one
        # is reached only through device.sdk_device_index. Never subtract here.
        if not self._opened:
            self._guard("Open camera", self._device.open, 1)
            self._opened = True
        # Program THIS burst's ROI and exposure before grabbing. Configuration
        # otherwise happens only when the grab thread starts, so the burst
        # inherits whatever the preview last set -- and the sensor keeps the
        # frame period that went with it: run 2026-08-13-09-18-35 delivered
        # correct 320x64 frames at the 320x120 period (556 us, 1798 fps instead
        # of 2624), because the preview had been started on the taller ROI. A
        # camera that is still grabbing ignores the new ROI, so stop first, and
        # the size check in the grab loop cannot catch it: the frames are the
        # right shape.
        self._guard("Stop grabbing", self._device.stop)
        self._guard("Configure camera", self._device.configure, cfg)
        self._guard("Start grabbing", self._device.start)

        stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        run_name = capture_image.with_label(
            f"piston_{stamp}_{cfg.width}x{cfg.height}", label)
        output_dir = injection_extract.make_dest_dir(
            Path(run_name), self._burst_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        self._bus.publish("capture_started", output_dir=str(output_dir),
                          duration_s=duration_s,
                          size=f"{cfg.width}x{cfg.height}")

        clones, ticks, block_ids = [], [], []
        truncated = False
        started = time.perf_counter()
        deadline = started + duration_s
        try:
            while time.perf_counter() < deadline:
                if cancel is not None and cancel():
                    break               # the operator stopped it, not a fault
                frame = self._guard("Get frame", self._device.grab, 1000)
                if frame is None:
                    # The camera stopped delivering with time left on the
                    # clock. Everything grabbed so far is kept -- but see
                    # BurstResult.truncated: nothing downstream can infer this.
                    truncated = True
                    break
                try:
                    self._check_size(frame, cfg)
                    clones.append(
                        self._guard("Clone frame", self._device.clone, frame))
                    ticks.append(frame.timestamp)
                    block_ids.append(frame.block_id)
                finally:
                    self._guard("Release frame", self._device.release, frame)

            elapsed = time.perf_counter() - started
            self._require_frames(clones)
            fps = len(clones) / elapsed if elapsed > 0 else 0.0
            for number, clone in enumerate(clones, start=1):
                self._guard("Save frame", self._device.save, clone,
                            capture_image.make_frame_path(
                                output_dir, prefix, number, ext))
            result = BurstResult(output_dir, len(clones), fps,
                                 _dropped(block_ids), elapsed, truncated)
            _write_meta(output_dir, result, ticks, cfg)
        finally:
            for clone in clones:
                self._guard("Release frame", self._device.release, clone)

        # This payload is all a UI gets -- the Tk build's "N frame(s) dropped"
        # warning line lives here now.
        self._bus.publish("capture_done", output_dir=str(output_dir),
                          frames=result.frames, fps=result.fps,
                          dropped=result.dropped, truncated=result.truncated)
        return result

    def close(self):
        """Release the device, if this worker ever opened it.

        The burst deliberately opens ONCE and leaves the camera open (see
        ``capture_piston``), so something above has to decide when the process
        is finished with it -- that owner is ``JobManager.close``. Idempotent,
        because shutdown can be reached more than once.
        """
        if self._opened:
            self._opened = False
            self._guard("Close camera", self._device.close)

    @staticmethod
    def _guard(what, call, *args):
        """Give every layer above this one a SINGLE exception type to catch.

        ``ImvCamera`` reports SDK failures as plain ``RuntimeError`` (through
        ``capture_image.check``) while ``FakeCamera`` raises ``CameraError``.
        The adapter cannot reconcile the two -- it is deliberately free of both
        ``try`` and logic -- so the normalisation belongs here.
        """
        try:
            return call(*args)
        except CameraError:
            raise                       # already the right type; do not rewrap
        except RuntimeError as exc:
            raise CameraError(f"{what} failed: {exc}") from exc

    @staticmethod
    def _check_size(frame, cfg):
        # The scale calibration is made at this ROI, so a burst at any other
        # size would be measured against the wrong magnification -- refuse it
        # instead of producing mm that look fine and are silently wrong.
        if (frame.width, frame.height) != (cfg.width, cfg.height):
            raise WrongFrameSize(
                f"The camera is streaming {frame.width}x{frame.height}, but "
                f"this capture must be {cfg.width}x{cfg.height} (the size the "
                "scale calibration was made at). Stop and restart the preview "
                "so the ROI is re-applied, then try again.")

    @staticmethod
    def _require_frames(clones):
        if not clones:
            raise RuntimeError(
                "No frames were grabbed - check the camera and lighting.")


def _dropped(block_ids):
    """Frames the camera dropped, counted from the gaps they leave behind."""
    if len(block_ids) < 2:
        return 0
    return max(0, (block_ids[-1] - block_ids[0] + 1) - len(block_ids))


def _write_meta(output_dir, result, ticks, cfg):
    base = ticks[0] if ticks else 0
    (output_dir / piston_track.CAPTURE_META_NAME).write_text(json.dumps({
        "fps": result.fps,
        # Per-frame SDK timestamp relative to the first frame, in RAW TICKS.
        # Nominally microseconds, but the vendor wrapper does not document the
        # unit, so measure_piston.resolve_timebase infers it against this
        # measured fps before trusting it -- see the module docstring.
        "frame_times_us": [tick - base for tick in ticks],
        "captured": result.frames, "dropped": result.dropped,
        "elapsed_s": result.elapsed_s,
        # Travels with the frames, so a run imported later still says whether
        # the stroke it holds is the whole stroke. See BurstResult.truncated.
        "truncated": result.truncated,
        "aspect": f"{cfg.width}x{cfg.height}",
        "width": cfg.width, "height": cfg.height,
    }), encoding="utf-8")
