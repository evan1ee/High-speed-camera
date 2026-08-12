#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Everything that runs on the persistent camera thread.

One worker owns the open camera for the whole session: it streams preview
frames, runs the burst capture in place (so Capture starts instantly), and
serves single-still requests registered via
:meth:`hsc.gui.capture.CaptureMixin.register_still_request`. It talks back to
the UI thread only through ``output_queue`` / ``preview_queue``.
"""

import json
import time
from ctypes import byref, c_void_p, string_at
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from hsc import capture_image
from hsc import frame_writer
from hsc import injection_extract
from hsc import monitor
from hsc import piston_track
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
                self.preview_queue.put((
                    "ERROR",
                    "No camera found - check the USB cable, camera power, "
                    "and that the camera driver is installed on this PC.",
                ))
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

                # Piston mode: a plain fixed-length burst that keeps every
                # frame and records its timestamps (see _do_piston_capture).
                if self.piston_requested.is_set():
                    self.piston_abort.clear()
                    try:
                        self._do_piston_capture(cam, sdk, self.piston_params)
                    except Exception as exc:
                        self.output_queue.put(("PISTON_CAPTURE_ERROR", str(exc)))
                    finally:
                        self.piston_requested.clear()
                        self.piston_abort.clear()
                    continue

                # Monitor mode: continuous grab + online injection detection,
                # until the user clicks Stop Monitoring.
                if self.monitor_requested.is_set():
                    try:
                        self._do_monitor(cam, sdk, self.monitor_params)
                    except Exception as exc:
                        self.output_queue.put(("CAPTURE_ERROR", f"Monitor: {exc}"))
                    finally:
                        self.monitor_requested.clear()
                        self.monitor_stop.clear()
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

    def _do_piston_capture(self, cam, sdk, params):
        """Fixed-length burst for a piston run: keep EVERY frame and record
        each one's SDK block id + timestamp.

        Deliberately separate from :meth:`_do_capture` rather than a flag
        inside it: the spray path's detect-before-write branch keys off the
        *jet's* motion signal, which says nothing about the piston, and keeping
        the two loops apart means the tuned spray pipeline cannot regress when
        this one changes. The timestamps are what make a speed curve possible
        -- frame index is not time when the camera free-runs and can drop
        frames (``blockId`` gaps reveal exactly that).
        """
        ok = sdk["IMV_OK"]
        suffix = params.ext if params.ext.startswith(".") else f".{params.ext}"
        capture_image.save_type_for(Path(f"frame{suffix}"), sdk)
        stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        run_name = capture_image.with_label(
            f"piston_{stamp}_{params.width}x{params.height}",
            getattr(params, "label", ""))
        output_dir = injection_extract.make_dest_dir(
            Path(run_name), Path(params.burst_dir))
        output_dir.mkdir(parents=True, exist_ok=True)

        self.output_queue.put(("STATUS", "Capturing piston..."))
        self.output_queue.put(
            f"Capturing piston for {params.duration:.3f}s at "
            f"{params.width}x{params.height} -- fire the injector now.\n")

        cloned_frames = []
        ticks = []
        block_ids = []
        started_at = time.perf_counter()
        deadline = started_at + params.duration
        try:
            while (time.perf_counter() < deadline
                   and not self.piston_abort.is_set()):
                frame = sdk["IMV_Frame"]()
                if cam.IMV_GetFrame(frame, 1000) != ok:
                    continue
                try:
                    # The scale calibration is made at this ROI, so a burst at
                    # any other size would be measured against the wrong
                    # magnification -- refuse it instead of producing mm that
                    # look fine and are silently wrong.
                    got = (int(frame.frameInfo.width), int(frame.frameInfo.height))
                    if got != (params.width, params.height):
                        raise RuntimeError(
                            f"The camera is streaming {got[0]}x{got[1]}, but a "
                            f"piston capture must be {params.width}x"
                            f"{params.height} (the size the scale calibration "
                            "was made at). Stop and restart the preview so the "
                            "ROI is re-applied, then try again.")
                    clone_frame = sdk["IMV_Frame"]()
                    capture_image.check(
                        cam.IMV_CloneFrame(frame, clone_frame), ok, "Clone frame")
                    cloned_frames.append(clone_frame)
                    ticks.append(int(frame.frameInfo.timeStamp))
                    block_ids.append(int(frame.frameInfo.blockId))
                finally:
                    cam.IMV_ReleaseFrame(frame)

            elapsed = time.perf_counter() - started_at
            captured = len(cloned_frames)
            if not captured:
                raise RuntimeError(
                    "No frames were grabbed - check the camera and lighting.")
            fps = captured / elapsed if elapsed > 0 else 0.0
            self.output_queue.put(
                f"Captured {captured} frames in {elapsed:.3f}s, "
                f"capture FPS: {fps:.1f}\n")

            save_start = time.perf_counter()
            for frame_no, clone_frame in enumerate(cloned_frames, start=1):
                capture_image.save_frame(
                    cam, clone_frame,
                    capture_image.make_frame_path(
                        output_dir, params.prefix, frame_no, suffix),
                    sdk)
            save_elapsed = time.perf_counter() - save_start

            dropped = 0
            if len(block_ids) >= 2 and block_ids[-1] >= block_ids[0]:
                dropped = max(
                    0, (block_ids[-1] - block_ids[0] + 1) - len(block_ids))
            base = ticks[0] if ticks else 0
            meta = {
                "fps": fps,
                # Per-frame SDK timestamp relative to the first frame. Nominally
                # microseconds; the vendor wrapper does not document the tick
                # unit, so measure_piston.resolve_timebase verifies/infers it
                # against this measured fps before trusting it.
                "frame_times_us": [t - base for t in ticks],
                "captured": captured,
                "dropped": dropped,
                "elapsed_s": elapsed,
                "aspect": params.aspect,
                "width": params.width,
                "height": params.height,
            }
            try:
                (output_dir / piston_track.CAPTURE_META_NAME).write_text(
                    json.dumps(meta), encoding="utf-8")
            except OSError as exc:
                self.output_queue.put(f"[Piston warning] no timing file: {exc}\n")
            if dropped:
                self.output_queue.put(
                    f"[Piston warning] {dropped} frame(s) dropped by the "
                    f"camera; timing uses the recorded timestamps.\n")
            self.output_queue.put(
                f"Saved {captured} frames to {output_dir} "
                f"in {save_elapsed:.3f}s\n")

            self.output_queue.put((
                "PISTON_CAPTURE_DONE",
                {
                    "dir": str(output_dir),
                    "frames": captured,
                    "fps": fps,
                    "dropped": dropped,
                    "elapsed": elapsed,
                },
            ))
        finally:
            for clone_frame in cloned_frames:
                cam.IMV_ReleaseFrame(clone_frame)

    def _do_monitor(self, cam, sdk, params):
        """Continuous grab + online detection until Stop Monitoring.

        Hot path per frame: grab -> np copy -> release -> engine.feed ->
        throttled preview. Event frames are written by the background
        EventWriter; nothing in this loop touches the disk.
        """
        ok = sdk["IMV_OK"]
        before = params.before if params is not None else 30
        after = params.after if params is not None else 30
        # Snapshot on the camera thread: _dispatch_monitor_event must never
        # touch a Tk variable.
        self.monitor_label = getattr(params, "label", "") if params else ""
        eng = monitor.MonitorEngine(before=before, after=after)
        writer = frame_writer.EventWriter(
            lambda d, saved_ok, msg: self.output_queue.put(
                ("MONITOR_SAVED", (d, saved_ok, msg))))
        self.output_queue.put(("STATUS", "MONITORING (armed)"))
        self.output_queue.put(
            "Monitoring started. Fire injections at will; "
            "click Stop Monitoring to finish.\n")
        n_events = 0
        last_preview = 0.0
        try:
            while not (self.monitor_stop.is_set() or self.preview_stop.is_set()):
                frame = sdk["IMV_Frame"]()
                ret = cam.IMV_GetFrame(frame, 1000)
                if ret != ok:
                    continue
                try:
                    info = frame.frameInfo
                    w, h = info.width, info.height
                    flat = np.frombuffer(
                        string_at(frame.pData, w * h), dtype=np.uint8)
                    gray = flat.reshape(h, w).copy()
                finally:
                    cam.IMV_ReleaseFrame(frame)

                event = eng.feed(gray)
                now = time.perf_counter()
                if now - last_preview > 0.04:            # ~25 fps preview
                    last_preview = now
                    self.preview_queue.put(("IMAGE", Image.fromarray(gray)))
                if event is not None:
                    if event["discarded"]:
                        self.output_queue.put(
                            f"[Monitor] ignored disturbance: {event['discarded']}\n")
                    else:
                        n_events += 1
                        self._dispatch_monitor_event(
                            event, writer, before, after, n_events)
            # Stop pressed mid-jet: close and keep the partial event (it is
            # saved AND processed, like any completed event).
            tail = eng.flush()
            if tail is not None:
                if tail["discarded"]:
                    self.output_queue.put(
                        f"[Monitor] ignored disturbance: {tail['discarded']}\n")
                else:
                    n_events += 1
                    self._dispatch_monitor_event(
                        tail, writer, before, after, n_events)
        finally:
            writer.close()
            discarded = eng.stats["discarded"]
            note = f" ({discarded} disturbance(s) ignored)" if discarded else ""
            self.output_queue.put((
                "MONITOR_STOPPED",
                f"Monitoring stopped: {n_events} injection(s){note}, "
                f"{eng.stats['fed']} frames examined."))

    def _dispatch_monitor_event(self, event, writer, before, after, n_events):
        """Reserve the event's folder, queue the async write, and post the
        make_result-shaped payload the UI holds until MONITOR_SAVED."""
        h, w = event["frames"][0].shape
        # Second-resolution stamp; make_dest_dir uniquifies if two events
        # close within the same second.
        stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        dest_dir = injection_extract.make_dest_dir(
            Path(capture_image.with_label(f"monitor_{stamp}_{w}x{h}",
                                          self.monitor_label)),
            INJECTION_DIR)
        # Create the folder NOW (cheap, once per event) so the next event's
        # make_dest_dir sees it and picks a unique name even while the
        # writer is still working through its queue.
        dest_dir.mkdir(parents=True, exist_ok=True)
        meta = smart_save.make_meta(event["bounds"], event["window"],
                                    "monitor (online)")
        writer.submit(str(dest_dir), event["names"], event["frames"], meta)
        result = smart_save.make_result(
            event["seq_names"], event["seq_signal"], event["bounds"],
            event["window"], source_dir="monitor", dest_dir=str(dest_dir),
            before=before, after=after, method="monitor (online)")
        note = f" [{event['dropped_note']}]" if event["dropped_note"] else ""
        self.output_queue.put(
            f"Injection #{n_events} detected -> {dest_dir.name} "
            f"({len(event['names'])} frames){note}\n")
        self.output_queue.put(
            ("STATUS", f"MONITORING (armed) - {n_events} injection(s)"))
        self.output_queue.put(("MONITOR_EVENT", result))

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
