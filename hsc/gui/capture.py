#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UI side of the capture pipeline: preview lifecycle, the Capture/Stop
buttons, input validation, and the still-grab request registry that feature
modules use to get a single frame from the already-running camera thread.
"""

import queue
import threading
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageTk

from hsc import capture_image
from hsc.gui.config import ROOT


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
        # Capture chain flag: CAPTURE_DONE -> find injection -> make video ->
        # measure. Stays set until the video finishes (or a step fails).
        self.auto_measure_pending = False
        # Single-still requests served by the camera worker between preview
        # frames (angle block, scale, block measure, nozzle reference, ...).
        self._still_requests = []

        self.duration_var = tk.StringVar(value="4.0")
        self.aspect_var = tk.StringVar(value="320x240")
        self.exposure_var = tk.StringVar(value="500")
        self.camera_index_var = tk.StringVar(value="1")
        self.output_dir_var = tk.StringVar(value=str(ROOT / "captures"))
        self.ext_var = tk.StringVar(value=".bmp")
        self.defer_save_var = tk.BooleanVar(value=True)
        self.timestamp_dir_var = tk.BooleanVar(value=True)
        self.no_save_var = tk.BooleanVar(value=False)
        self.before_var = tk.StringVar(value="30")
        self.after_var = tk.StringVar(value="30")

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
        try:
            before = max(0, int(self.before_var.get()))
            after = max(0, int(self.after_var.get()))
        except ValueError:
            before, after = 30, 30
        return SimpleNamespace(
            duration=duration,
            no_save=self.no_save_var.get(),
            defer_save=self.defer_save_var.get(),
            timestamp_dir=self.timestamp_dir_var.get(),
            aspect=self.aspect_var.get(),
            width=width,
            height=height,
            ext=self.ext_var.get(),
            prefix="frame",
            burst_dir=self.output_dir_var.get(),
            before=before,
            after=after,
        )

    # ------------------------------------------------------------------
    # Preview / camera lifecycle
    # ------------------------------------------------------------------
    def _toggle_preview(self):
        if self.camera_thread and self.camera_thread.is_alive():
            self._stop_preview()
            return
        self._start_preview()

    def _start_preview(self):
        if self.camera_thread and self.camera_thread.is_alive():
            return

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
    # Capture button
    # ------------------------------------------------------------------
    def _run_capture(self):
        if self.capture_requested.is_set():
            return

        try:
            params = self._build_capture_params()
        except ValueError as exc:
            self.status_var.set(str(exc))
            return

        self.capture_params = params
        self.last_output_dir = None
        self.log_text.delete("1.0", tk.END)
        self.run_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)

        # Make sure the camera is open and grabbing; the worker picks up the
        # request on its next loop iteration and starts the burst immediately.
        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()

        self.capture_abort.clear()
        self.capture_requested.set()
        self.status_var.set("Capturing...")

    def _stop_capture(self):
        if self.capture_requested.is_set():
            self.capture_abort.set()
            self.status_var.set("Aborting capture...")
        else:
            self._stop_preview()

    def _on_capture_done(self, payload):
        self.status_var.set("Done")
        info = payload if isinstance(payload, dict) else {"dir": payload}
        self.last_output_dir = Path(info["dir"])
        self.run_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        # Auto-find the injection right after a saved capture, then
        # make the slow-motion video, then measure the spray angle.
        if not (self.capture_params and self.capture_params.no_save):
            self.auto_measure_pending = True
            if info.get("bounds") is not None and info.get("signal"):
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
        self.run_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)

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
                        self.run_button.configure(state=tk.NORMAL)
                        self.stop_button.configure(state=tk.DISABLED)
                    # Release any other pending camera request so its button is
                    # not stranded disabled when the worker dies (e.g. the camera
                    # fails to enumerate after the operator clicked Calibrate).
                    for req in self._still_requests:
                        if req.event.is_set():
                            req.event.clear()
                            for name in req.buttons:
                                getattr(self, name).configure(state=tk.NORMAL)

        except queue.Empty:
            pass

        if latest_image is not None:
            self._render_preview(latest_image)

        self.after(50, self._drain_preview_queue)

    def _render_preview(self, image):
        """Scale the live frame to fill the preview pane while keeping the
        exact aspect ratio and pixel content of the captured frame."""
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
        self.preview_photo = ImageTk.PhotoImage(resized)
        self.preview_label.configure(image=self.preview_photo, text="")
