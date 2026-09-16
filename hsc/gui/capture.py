#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UI side of the capture pipeline: preview lifecycle, the Capture/Stop
buttons, input validation, and the still-grab request registry that feature
modules use to get a single frame from the already-running camera thread.
"""

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image, ImageTk

from hsc import capture_image
from hsc import reference_lines
from hsc.gui.config import PAD_AFTER, PAD_BEFORE, ROOT


class CaptureMixin:
    """Preview + burst-capture controls (the camera thread itself lives in
    :class:`hsc.gui.camera_worker.CameraWorkerMixin`)."""

    QUEUE_HANDLERS = {
        "CAPTURE_DONE": "_on_capture_done",
        "CAPTURE_ERROR": "_on_capture_error",
    }

    def _init_capture_state(self):
        self.camera_thread = None
        self.preview_stop = threading.Event()
        self.capture_requested = threading.Event()
        self.capture_abort = threading.Event()
        self.capture_params = None
        self.preview_photo = None
        # Last live frame, re-rendered on pane resize so the preview always
        # fits the window (including right after launch / maximizing).
        self._last_preview_image = None
        self._preview_resize_job = None
        # Saved nozzle reference (red tip line / blue centerline / target
        # rectangle) overlaid live on the preview so the jet can be aimed into
        # the band while capturing. Loaded on preview start / after Set
        # Reference; drawn only when its image_size matches the preview frame.
        self._preview_reference = None
        # Capture chain flag: CAPTURE_DONE -> find injection -> measure ->
        # make video. Stays set until measurement finishes (or a step fails).
        self.auto_measure_pending = False
        # Wall-clock start of the find-injection -> measure pipeline; the
        # total is logged when the auto-chained measurement finishes (for
        # comparing the speed of different settings, e.g. smart save on/off).
        self._pipeline_t0 = None
        # Single-still requests served by the camera worker between preview
        # frames (angle block, scale, block measure, nozzle reference, ...).
        self._still_requests = []

        self.duration_var = tk.StringVar(value="4.0")
        self.aspect_var = tk.StringVar(value="320x240")
        self.exposure_var = tk.StringVar(value="500")
        self.camera_index_var = tk.StringVar(value="1")
        # The data root: captures\, injection images\, measure\ live under it.
        self.output_dir_var = tk.StringVar(value=str(ROOT))
        self.ext_var = tk.StringVar(value=".bmp")
        self.show_ref_var = tk.BooleanVar(value=True)
        self.smart_save_var = tk.BooleanVar(value=False)

    def register_still_request(self, event, prefix, done_kind, error_kind,
                               dest_dir, buttons):
        """Register a "grab one still" request slot with the camera worker.

        *event* is the :class:`threading.Event` the feature sets to request a
        frame; the worker saves it to *dest_dir* as ``<prefix>_<ts>.bmp`` and
        posts ``(done_kind, path)`` (or ``(error_kind, msg)``). *buttons* are
        widget attribute names re-enabled if the camera stops with the request
        still pending. Requests are served in registration order.
        """
        self._still_requests.append(SimpleNamespace(
            event=event, prefix=prefix, done_kind=done_kind,
            error_kind=error_kind, dest_dir=dest_dir, buttons=tuple(buttons),
        ))

    def _validate_inputs(self):
        try:
            duration = float(self.duration_var.get())
            if duration <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("Capture time must be a positive number.")

        try:
            exposure = float(self.exposure_var.get())
            if exposure <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("Exposure must be a positive number.")

        try:
            camera_index = int(self.camera_index_var.get())
            if camera_index <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("Camera index must be a positive integer.")

        return duration, exposure, camera_index

    def _build_preview_args(self):
        _, exposure, _ = self._validate_inputs()
        width, height = capture_image.ASPECT_PRESETS[self.aspect_var.get()]
        return SimpleNamespace(
            pixel_format="Mono8",
            width=width,
            height=height,
            center_roi=True,
            offset_x=None,
            offset_y=None,
            exposure_us=exposure,
            frame_rate=None,
        )

    def _build_capture_params(self):
        duration, _, _ = self._validate_inputs()
        width, height = capture_image.ASPECT_PRESETS[self.aspect_var.get()]
        return SimpleNamespace(
            duration=duration,
            # Fixed policy (former checkboxes): always capture-then-save
            # (defer_save avoids dropped frames at high FPS), never test-only,
            # always a fresh timestamp folder per run.
            no_save=False,
            defer_save=True,
            smart_save=self.smart_save_var.get(),
            timestamp_dir=True,
            aspect=self.aspect_var.get(),
            width=width,
            height=height,
            ext=self.ext_var.get(),
            prefix="frame",
            # Bursts land in <data folder>\captures\<run> (the field holds
            # the data root, not the captures folder itself).
            burst_dir=str(Path(self.output_dir_var.get()) / "captures"),
            before=PAD_BEFORE,
            after=PAD_AFTER,
        )

    # ------------------------------------------------------------------
    # Preview / camera lifecycle
    # ------------------------------------------------------------------
    def _toggle_preview(self):
        if self.camera_thread and self.camera_thread.is_alive():
            self._stop_preview()
            return
        self._start_preview()

    def _refresh_preview_reference(self):
        """Reload the saved nozzle reference for the live-preview overlay.

        Called on preview start and after Set Reference (and when the overlay
        checkbox is toggled), so the overlay always reflects the latest saved
        ``reference_lines.json``. Never raises into the UI callback.
        """
        try:
            self._preview_reference = reference_lines.load_reference()
        except Exception:
            self._preview_reference = None

    def _start_preview(self):
        if self.camera_thread and self.camera_thread.is_alive():
            return

        self._refresh_preview_reference()
        try:
            _, _, camera_index = self._validate_inputs()
            preview_args = self._build_preview_args()
        except ValueError as exc:
            self.status_var.set(str(exc))
            return

        self.preview_stop.clear()
        self.preview_button.configure(text="Stop Preview")
        self.status_var.set("Preview running...")
        self.camera_thread = threading.Thread(
            target=self._camera_worker,
            args=(camera_index, preview_args),
            daemon=True,
        )
        self.camera_thread.start()

    def _stop_preview(self):
        self.preview_stop.set()
        self.capture_abort.set()
        self.preview_button.configure(text="Start Preview")

    # ------------------------------------------------------------------
    # Capture button (toggles to "Stop Capture" while a burst is running)
    # ------------------------------------------------------------------
    def _run_capture(self):
        if self.capture_requested.is_set():
            # Second click = abort; the button resets on CAPTURE_DONE/ERROR.
            self.capture_abort.set()
            self.status_var.set("Aborting capture...")
            return

        try:
            params = self._build_capture_params()
        except ValueError as exc:
            self.status_var.set(str(exc))
            return

        self.capture_params = params
        self.last_output_dir = None
        self.log_text.delete("1.0", tk.END)
        self.run_button.configure(text="Stop Capture")

        # Make sure the camera is open and grabbing; the worker picks up the
        # request on its next loop iteration and starts the burst immediately.
        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()

        self.capture_abort.clear()
        self.capture_requested.set()
        self.status_var.set("Capturing...")

    def _on_capture_done(self, payload):
        self.status_var.set("Done")
        info = payload if isinstance(payload, dict) else {"dir": payload}
        self.last_output_dir = Path(info["dir"])
        self.run_button.configure(state=tk.NORMAL, text="Capture")
        # Auto-find the injection right after a saved capture, then measure
        # the spray angle, then make the slow-motion video.
        if self.capture_params and self.capture_params.no_save:
            self._pipeline_t0 = None       # no chain -> no total to report
        else:
            self.auto_measure_pending = True
            # Timer: find-injection start -> measurement finished.
            self._pipeline_t0 = time.perf_counter()
            if info.get("extract_result") is not None:
                # Smart save already wrote the injection window;
                # skip straight to the video+measure chain.
                self._on_extract_done(info["extract_result"])
            elif info.get("bounds") is not None and info.get("signal"):
                # Bounds were computed in RAM during the save phase;
                # just copy the window (no disk read-back).
                self._auto_copy_injection(info)
            elif info.get("signal"):
                self._auto_extract_from_signal(
                    info["files"], info["signal"]
                )
            else:
                self._find_injection(info["dir"])

    def _on_capture_error(self, payload):
        self.status_var.set(f"Error: {payload}")
        self._append_log(f"[Capture Error] {payload}\n")
        self.run_button.configure(state=tk.NORMAL, text="Capture")
        self._pipeline_t0 = None

    # ------------------------------------------------------------------
    # Preview queue draining / rendering
    # ------------------------------------------------------------------
    def _drain_preview_queue(self):
        latest_image = None
        try:
            while True:
                msg_type, payload = self.preview_queue.get_nowait()

                if msg_type == "IMAGE":
                    # Keep only the newest frame so the preview never lags.
                    latest_image = payload

                elif msg_type == "ERROR":
                    self.status_var.set(f"Preview error: {payload}")
                    self._append_log(f"[Preview Error] {payload}\n")

                elif msg_type == "STOPPED":
                    latest_image = None
                    self.preview_label.configure(image="", text="Preview stopped")
                    self.preview_photo = None
                    self.preview_button.configure(text="Start Preview")
                    # If a capture was pending when the camera stopped, release it.
                    if self.capture_requested.is_set():
                        self.capture_requested.clear()
                        self.run_button.configure(state=tk.NORMAL, text="Capture")
                    # Release any other pending camera request so its button is
                    # not stranded disabled when the worker dies (e.g. the camera
                    # fails to enumerate after the operator clicked Calibrate).
                    for req in self._still_requests:
                        if req.event.is_set():
                            req.event.clear()
                            for name in req.buttons:
                                getattr(self, name).configure(state=tk.NORMAL)
                    # Monitoring cannot continue without the camera; return
                    # the toggle + camera buttons to idle (idempotent).
                    self._reset_monitor_ui()

        except queue.Empty:
            pass

        if latest_image is not None:
            self._render_preview(latest_image)

        self.after(50, self._drain_preview_queue)

    def _on_preview_resize(self, _event=None):
        """Re-fit the last frame when the preview pane is resized (debounced;
        also fits the first frame right after launch)."""
        if self._last_preview_image is None:
            return
        if self._preview_resize_job is not None:
            self.after_cancel(self._preview_resize_job)

        def refit():
            self._preview_resize_job = None
            self._render_preview(self._last_preview_image)

        self._preview_resize_job = self.after(50, refit)

    def _render_preview(self, image):
        """Scale the live frame to fill the preview pane while keeping the
        exact aspect ratio and pixel content of the captured frame."""
        self._last_preview_image = image
        avail_w = self.preview_frame.winfo_width() - 24
        avail_h = self.preview_frame.winfo_height() - 40
        if avail_w < 40 or avail_h < 40:
            avail_w, avail_h = 480, 360

        src_w, src_h = image.size
        scale = min(avail_w / src_w, avail_h / src_h)
        if scale <= 0:
            scale = 1.0
        target = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))

        resized = image.resize(target, Image.BILINEAR)

        ref = self._preview_reference
        if (self.show_ref_var.get() and ref
                and ref.get("image_size") == [src_w, src_h]):
            # Draw the saved reference on the scaled frame using the SAME
            # renderer the measured output uses, so preview and output line up.
            # Native ref coords are scaled by the display scale here.
            bgr = cv2.cvtColor(np.array(resized), cv2.COLOR_GRAY2BGR)
            reference_lines.draw_reference(bgr, ref, scale=scale)
            resized = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

        self.preview_photo = ImageTk.PhotoImage(resized)
        self.preview_label.configure(image=self.preview_photo, text="")
