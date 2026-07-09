#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Everything that runs on the persistent camera thread.

One worker owns the open camera for the whole session: it streams preview
frames, runs the burst capture in place (so Capture starts instantly), and
serves single-still requests registered via
:meth:`hsc.gui.capture.CaptureMixin.register_still_request`. It talks back to
the UI thread only through ``output_queue`` / ``preview_queue``.
"""

import time
from ctypes import byref, c_void_p, string_at
from pathlib import Path

import numpy as np
from PIL import Image

from hsc import capture_image
from hsc import injection_extract
from hsc import smart_save
from hsc.gui.config import INJECTION_DIR


class CameraWorkerMixin:
    """Camera-thread half of the capture pipeline."""

    def _camera_worker(self, camera_index, preview_args):
        sdk = None
        cam = None
        try:
            sdk = capture_image.load_sdk()
            device_list = capture_image.enum_devices(sdk)
            if device_list.nDevNum == 0:
                self.preview_queue.put(("ERROR", "No camera found."))
                return
            if camera_index < 1 or camera_index > device_list.nDevNum:
                self.preview_queue.put(("ERROR", f"Camera index must be 1..{device_list.nDevNum}"))
                return

            cam = sdk["MvCamera"]()
            ret = cam.IMV_CreateHandle(
                sdk["IMV_ECreateHandleMode"].modeByIndex,
                byref(c_void_p(camera_index - 1)),
            )
            capture_image.check(ret, sdk["IMV_OK"], "Create camera handle")
            capture_image.check(cam.IMV_Open(), sdk["IMV_OK"], "Open camera")
            capture_image.configure_camera(cam, sdk, preview_args)
            capture_image.check(cam.IMV_StartGrabbing(), sdk["IMV_OK"], "Start grabbing")

            while not self.preview_stop.is_set():
                # A capture was requested: run the burst using the camera that
                # is already open and grabbing, so it starts immediately.
                if self.capture_requested.is_set():
                    self.capture_abort.clear()
                    try:
                        self._do_capture(cam, sdk, self.capture_params)
                    except Exception as exc:
                        self.output_queue.put(("CAPTURE_ERROR", str(exc)))
                    finally:
                        self.capture_requested.clear()
                        self.capture_abort.clear()
                    continue

                # A single still was requested (angle block, scale reference,
                # block measure, nozzle reference, ...).
                pending = next(
                    (r for r in self._still_requests if r.event.is_set()), None
                )
                if pending is not None:
                    try:
                        self._grab_still(cam, sdk, pending.prefix,
                                         pending.done_kind, pending.dest_dir)
                    except Exception as exc:
                        self.output_queue.put((pending.error_kind, str(exc)))
                    finally:
                        pending.event.clear()
                    continue

                frame = sdk["IMV_Frame"]()
                ret = cam.IMV_GetFrame(frame, 1000)
                if ret != sdk["IMV_OK"]:
                    continue
                try:
                    width = frame.frameInfo.width
                    height = frame.frameInfo.height
                    size = frame.frameInfo.size
                    data = string_at(frame.pData, size)
                    image = Image.frombytes("L", (width, height), data[: width * height])
                    self.preview_queue.put(("IMAGE", image))
                finally:
                    cam.IMV_ReleaseFrame(frame)
                time.sleep(0.04)
        except Exception as exc:
            self.preview_queue.put(("ERROR", str(exc)))
        finally:
            if cam and cam.handle:
                if cam.IMV_IsGrabbing():
                    cam.IMV_StopGrabbing()
                if cam.IMV_IsOpen():
                    cam.IMV_Close()
                cam.IMV_DestroyHandle()
            self.preview_queue.put(("STOPPED", None))

    def _do_capture(self, cam, sdk, params):
        ok = sdk["IMV_OK"]
        suffix = params.ext if params.ext.startswith(".") else f".{params.ext}"
        capture_image.save_type_for(Path(f"frame{suffix}"), sdk)
        output_dir = capture_image.make_run_output_dir(Path(params.burst_dir), params)
        if not params.no_save:
            output_dir.mkdir(parents=True, exist_ok=True)

        self.output_queue.put(("STATUS", "Capturing..."))
        self.output_queue.put(f"Capturing for {params.duration:.3f}s ...\n")

        captured = 0
        saved = 0
        cloned_frames = []
        started_at = time.perf_counter()
        deadline = started_at + params.duration

        try:
            while time.perf_counter() < deadline and not self.capture_abort.is_set():
                frame = sdk["IMV_Frame"]()
                ret = cam.IMV_GetFrame(frame, 1000)
                if ret != ok:
                    continue
                try:
                    captured += 1
                    if not params.no_save:
                        if params.defer_save:
                            clone_frame = sdk["IMV_Frame"]()
                            capture_image.check(
                                cam.IMV_CloneFrame(frame, clone_frame), ok, "Clone frame"
                            )
                            cloned_frames.append(clone_frame)
                        else:
                            output_path = capture_image.make_frame_path(
                                output_dir, params.prefix, captured, suffix
                            )
                            capture_image.save_frame(cam, frame, output_path, sdk)
                            saved += 1
                finally:
                    cam.IMV_ReleaseFrame(frame)

            elapsed = time.perf_counter() - started_at
            fps = captured / elapsed if elapsed > 0 else 0.0

            saved_paths = []
            motion_signal = None
            small_frames = []
            extract_result = None
            bounds = None
            ds = injection_extract.DOWNSAMPLE
            smart = bool(getattr(params, "smart_save", False)
                         and params.defer_save and not params.no_save)
            if cloned_frames:
                # Pass A (RAM only): motion signal + downsampled copies.
                # No disk I/O here -- this is what lets smart mode decide the
                # window BEFORE anything is written.
                motion_signal = []
                prev_pixels = None
                for clone_frame in cloned_frames:
                    info = clone_frame.frameInfo
                    w, h = info.width, info.height
                    n_pixels = w * h
                    flat = np.frombuffer(
                        string_at(clone_frame.pData, n_pixels), dtype=np.uint8
                    )
                    pixels = flat.astype(np.int16)
                    if prev_pixels is not None and prev_pixels.shape == pixels.shape:
                        motion_signal.append(
                            float(
                                np.count_nonzero(
                                    np.abs(pixels - prev_pixels)
                                    > injection_extract.DIFF_THRESH
                                )
                            )
                        )
                    else:
                        motion_signal.append(0.0)
                    prev_pixels = pixels
                    small_frames.append(flat.reshape(h, w)[::ds, ::ds].copy())

                # Detect BEFORE saving (same detection code as always; the
                # window math lives in smart_save.plan_window, proven equal
                # to build_result's by test).
                window = None
                try:
                    bounds, window = smart_save.plan_window(
                        motion_signal,
                        lambda i: small_frames[i].astype(np.int16),
                        len(small_frames), params.before, params.after,
                    )
                except Exception as exc:
                    bounds, window = None, None
                    self.output_queue.put(f"[Detect warning] {exc}\n")

                self.output_queue.put(
                    f"Captured {captured} frames in {elapsed:.3f}s, "
                    f"capture FPS: {fps:.1f}\n"
                )

                save_start = time.perf_counter()
                if smart and bounds is not None:
                    # Smart save: write ONLY the window, directly into the
                    # injection-images run folder. Frame names keep their
                    # original burst indices, matching what the legacy
                    # save-then-copy pipeline produces.
                    dest_dir = injection_extract.make_dest_dir(
                        output_dir, INJECTION_DIR)
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    names = [
                        capture_image.make_frame_path(
                            dest_dir, params.prefix, i + 1, suffix).name
                        for i in range(len(cloned_frames))
                    ]
                    # Meta first, so a mid-write disk failure still leaves a
                    # self-describing partial folder.
                    smart_save.write_meta(dest_dir, bounds, window,
                                          "in-memory (smart save)")
                    for i in range(window[0], window[1] + 1):
                        capture_image.save_frame(
                            cam, cloned_frames[i], dest_dir / names[i], sdk)
                        saved += 1
                    extract_result = smart_save.make_result(
                        names, motion_signal, bounds, window,
                        source_dir=str(output_dir), dest_dir=str(dest_dir),
                        before=params.before, after=params.after,
                        method="in-memory (smart save)")
                    save_elapsed = time.perf_counter() - save_start
                    self.output_queue.put(
                        f"Smart save: kept {saved} of {captured} frames "
                        f"-> {dest_dir} in {save_elapsed:.3f}s\n"
                    )
                    if params.timestamp_dir:
                        try:                 # captures run dir stays empty
                            output_dir.rmdir()
                        except OSError:
                            pass
                else:
                    if smart:
                        self.output_queue.put(
                            "Smart save: no injection detected -- "
                            "saving the full burst as usual.\n"
                        )
                    for frame_no, clone_frame in enumerate(cloned_frames, start=1):
                        output_path = capture_image.make_frame_path(
                            output_dir, params.prefix, frame_no, suffix
                        )
                        capture_image.save_frame(cam, clone_frame, output_path, sdk)
                        saved += 1
                        saved_paths.append(str(output_path))
                    save_elapsed = time.perf_counter() - save_start
                    self.output_queue.put(
                        f"Saved {saved} cloned frames to {output_dir} "
                        f"in {save_elapsed:.3f}s\n"
                    )
            else:
                verb = "Captured" if params.no_save else "Saved"
                where = "" if params.no_save else f" to {output_dir}"
                self.output_queue.put(f"{verb} {captured} frames{where}\n")
                self.output_queue.put(
                    f"Elapsed: {elapsed:.3f}s, effective FPS: {fps:.1f}\n"
                )

            self.output_queue.put(
                (
                    "CAPTURE_DONE",
                    {
                        "dir": str(output_dir),
                        "files": saved_paths,
                        "signal": motion_signal,
                        "bounds": bounds,
                        "before": params.before,
                        "after": params.after,
                        "extract_result": extract_result,
                    },
                )
            )
        finally:
            for clone_frame in cloned_frames:
                cam.IMV_ReleaseFrame(clone_frame)

    def _grab_still(self, cam, sdk, prefix, done_kind, dest_dir):
        """Grab one frame, save it to *dest_dir*, and post its path to the GUI."""
        frame = sdk["IMV_Frame"]()
        ret = cam.IMV_GetFrame(frame, 1000)
        if ret != sdk["IMV_OK"]:
            self.output_queue.put((done_kind.replace("_CAPTURED", "_ERROR"),
                                   "No frame grabbed."))
            return
        try:
            w = frame.frameInfo.width
            h = frame.frameInfo.height
            data = string_at(frame.pData, w * h)
            image = Image.frombytes("L", (w, h), data)
        finally:
            cam.IMV_ReleaseFrame(frame)
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.bmp"
        image.save(path)
        self.output_queue.put((done_kind, str(path)))
