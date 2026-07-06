#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import queue
import threading
import time
import tkinter as tk
from ctypes import byref, c_void_p, string_at
from pathlib import Path
from tkinter import filedialog, ttk
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageTk

from hsc import calibrate_scale
from hsc import calibrate_ui
from hsc import capture_image
from hsc import injection_extract
from hsc import make_video
from hsc import measure_angle
from hsc import measure_block
from hsc import reference_lines
from hsc import reference_ui
from hsc.app_paths import data_root


ROOT = data_root()
INJECTION_DIR = ROOT / "injection images"
MEASURE_DIR = ROOT / "measure"
BLOCK_DIR = MEASURE_DIR / "angle_block"
SCALE_DIR = MEASURE_DIR / "block"
REFERENCE_DIR = MEASURE_DIR / "reference"
ASPECT_PRESETS = ("1:1", "2:1", "4:3", "16:9", "320x240")
IMAGE_EXTENSIONS = (".bmp", ".png", ".jpg", ".tif")


class CaptureGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("High Speed Camera Capture")
        self.geometry("980x680")
        self.minsize(860, 600)
        # Launch maximized.
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-zoomed", True)

        self.output_queue = queue.Queue()
        self.preview_queue = queue.Queue()
        self.camera_thread = None
        self.preview_stop = threading.Event()
        self.capture_requested = threading.Event()
        self.capture_abort = threading.Event()
        self.capture_params = None
        self.last_output_dir = None
        self.last_injection_dir = None
        self.preview_photo = None
        self.extract_thread = None
        self.measure_thread = None
        self.block_thread = None
        self.video_thread = None
        self.block_requested = threading.Event()
        self.scale_requested = threading.Event()
        self.scale_thread = None
        self._scale_auto = False
        self.measblock_requested = threading.Event()
        self.measblock_thread = None
        self.reference_requested = threading.Event()
        self.auto_measure_pending = False

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
        self.measure_start_var = tk.StringVar(value="10")
        self.measure_end_var = tk.StringVar(value="20")
        self.line_len_var = tk.StringVar(value="Full")
        self.ref_mm_var = tk.StringVar(value="10")
        self._block_line_frac = None

        self._build_layout()
        self.after(100, self._drain_output_queue)
        self.after(50, self._drain_preview_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Automatically start the live preview as soon as the GUI launches.
        self.after(200, self._start_preview)

    def _build_layout(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.BOTH, expand=True)

        controls = ttk.LabelFrame(top, text="Capture Settings", padding=12)
        controls.pack(side=tk.LEFT, fill=tk.Y)
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        self.preview_frame = ttk.LabelFrame(top, text="Live Preview", padding=8)
        self.preview_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(12, 0))
        self.preview_label = ttk.Label(self.preview_frame, text="Starting preview...", anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        self._label_entry(controls, "Capture time (s)", self.duration_var, 0, 0)
        self._label_combo(controls, "Aspect preset", self.aspect_var, ASPECT_PRESETS, 0, 2)
        self._label_entry(controls, "Exposure (us)", self.exposure_var, 1, 0)
        self._label_entry(controls, "Camera index", self.camera_index_var, 1, 2)
        self._label_combo(controls, "Image type", self.ext_var, IMAGE_EXTENSIONS, 2, 0)

        ttk.Label(controls, text="Output base folder").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(controls, textvariable=self.output_dir_var).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=(8, 0)
        )
        ttk.Button(controls, text="Browse", command=self._browse_output_dir).grid(
            row=3, column=3, sticky="ew", pady=(8, 0)
        )

        checks = ttk.Frame(controls)
        checks.grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Checkbutton(checks, text="Defer save", variable=self.defer_save_var).pack(side=tk.LEFT)
        ttk.Checkbutton(checks, text="Timestamp folder", variable=self.timestamp_dir_var).pack(
            side=tk.LEFT, padx=(16, 0)
        )
        ttk.Checkbutton(checks, text="Test only, do not save", variable=self.no_save_var).pack(
            side=tk.LEFT, padx=(16, 0)
        )

        self._label_entry(controls, "Frames before injection", self.before_var, 5, 0)
        self._label_entry(controls, "Frames after injection", self.after_var, 5, 2)
        self._label_entry(controls, "Measure from (Nth)", self.measure_start_var, 6, 0)
        self._label_entry(controls, "Measure to (Nth)", self.measure_end_var, 6, 2)
        self._label_combo(controls, "Line length", self.line_len_var,
                          ("Full", "3/4", "2/3", "1/2"), 7, 0)
        self._label_entry(controls, "Cal. distance (mm)", self.ref_mm_var, 7, 2)

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=(12, 8))
        self.preview_button = ttk.Button(actions, text="Stop Preview", command=self._toggle_preview)
        self.preview_button.pack(side=tk.LEFT)
        self.run_button = ttk.Button(actions, text="Capture", command=self._run_capture)
        self.run_button.pack(side=tk.LEFT, padx=(8, 0))
        self.stop_button = ttk.Button(actions, text="Stop", command=self._stop_capture, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        self.extract_button = ttk.Button(
            actions, text="Find Injection", command=self._find_injection
        )
        self.extract_button.pack(side=tk.LEFT, padx=(8, 0))
        self.measure_button = ttk.Button(
            actions, text="Measure", command=self._measure_injection
        )
        self.measure_button.pack(side=tk.LEFT, padx=(8, 0))
        self.block_button = ttk.Button(
            actions, text="Measure Angle Block", command=self._measure_block
        )
        self.block_button.pack(side=tk.LEFT, padx=(8, 0))
        self.video_button = ttk.Button(
            actions, text="Make Video", command=self._make_video
        )
        self.video_button.pack(side=tk.LEFT, padx=(8, 0))
        self.scale_button = ttk.Button(
            actions, text="Calibrate Scale", command=self._calibrate_scale
        )
        self.scale_button.pack(side=tk.LEFT, padx=(8, 0))
        self.autoscale_button = ttk.Button(
            actions, text="Auto Calibrate",
            command=lambda: self._calibrate_scale(auto=True),
        )
        self.autoscale_button.pack(side=tk.LEFT, padx=(8, 0))
        self.measblock_button = ttk.Button(
            actions, text="Measure Block", command=self._measure_block_size
        )
        self.measblock_button.pack(side=tk.LEFT, padx=(8, 0))
        self.reference_button = ttk.Button(
            actions, text="Set Reference", command=self._set_reference
        )
        self.reference_button.pack(side=tk.LEFT, padx=(8, 0))
        self.open_button = ttk.Button(actions, text="Open Last Folder", command=self._open_last_folder)
        self.open_button.pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(actions, textvariable=self.status_var).pack(side=tk.LEFT, padx=(16, 0))

        log_frame = ttk.LabelFrame(root, text="Output", padding=8)
        log_frame.pack(fill=tk.X)
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=10)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _label_entry(self, parent, label, variable, row, column):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", pady=(0, 8))
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=column + 1, sticky="ew", padx=(8, 16), pady=(0, 8)
        )

    def _label_combo(self, parent, label, variable, values, row, column):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", pady=(0, 8))
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.grid(row=row, column=column + 1, sticky="ew", padx=(8, 16), pady=(0, 8))

    def _browse_output_dir(self):
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(ROOT))
        if selected:
            self.output_dir_var.set(selected)

    def _append_log(self, text):
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)

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

                # A single still of the angle block was requested.
                if self.block_requested.is_set():
                    try:
                        self._grab_block_still(cam, sdk)
                    except Exception as exc:
                        self.output_queue.put(("BLOCK_ERROR", str(exc)))
                    finally:
                        self.block_requested.clear()
                    continue

                # A single still of the scale reference block was requested.
                if self.scale_requested.is_set():
                    try:
                        self._grab_still(cam, sdk, "scale", "SCALE_CAPTURED", SCALE_DIR)
                    except Exception as exc:
                        self.output_queue.put(("SCALE_ERROR", str(exc)))
                    finally:
                        self.scale_requested.clear()
                    continue

                # A single still to measure an unknown block against the scale.
                if self.measblock_requested.is_set():
                    try:
                        self._grab_still(cam, sdk, "measblock", "MEASBLOCK_CAPTURED", SCALE_DIR)
                    except Exception as exc:
                        self.output_queue.put(("MEASBLOCK_ERROR", str(exc)))
                    finally:
                        self.measblock_requested.clear()
                    continue

                # A single still of the nozzle to build the reference lines.
                if self.reference_requested.is_set():
                    try:
                        self._grab_still(cam, sdk, "nozzle", "REFERENCE_CAPTURED", REFERENCE_DIR)
                    except Exception as exc:
                        self.output_queue.put(("REFERENCE_ERROR", str(exc)))
                    finally:
                        self.reference_requested.clear()
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
            ds = injection_extract.DOWNSAMPLE
            if cloned_frames:
                save_start = time.perf_counter()
                # Build the motion signal AND keep a small downsampled copy of
                # every frame in RAM while saving, so the auto injection finder
                # needs no disk read-back of the new files.
                motion_signal = []
                prev_pixels = None
                for frame_no, clone_frame in enumerate(cloned_frames, start=1):
                    output_path = capture_image.make_frame_path(
                        output_dir, params.prefix, frame_no, suffix
                    )
                    capture_image.save_frame(cam, clone_frame, output_path, sdk)
                    saved += 1
                    saved_paths.append(str(output_path))

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
                    # Downsampled copy for the jet-presence (end) detection.
                    small_frames.append(flat.reshape(h, w)[::ds, ::ds].copy())

                save_elapsed = time.perf_counter() - save_start
                self.output_queue.put(
                    f"Captured {captured} frames in {elapsed:.3f}s, capture FPS: {fps:.1f}\n"
                )
                self.output_queue.put(
                    f"Saved {saved} cloned frames to {output_dir} in {save_elapsed:.3f}s\n"
                )
            else:
                verb = "Captured" if params.no_save else "Saved"
                where = "" if params.no_save else f" to {output_dir}"
                self.output_queue.put(f"{verb} {captured} frames{where}\n")
                self.output_queue.put(
                    f"Elapsed: {elapsed:.3f}s, effective FPS: {fps:.1f}\n"
                )

            # Detect injection bounds in RAM (onset from the motion signal,
            # end from jet presence in the downsampled frames) before the
            # cloned frames are released.
            bounds = None
            if motion_signal and small_frames:
                try:
                    bounds = injection_extract.detect_bounds_with_presence(
                        np.asarray(motion_signal, dtype=np.float64),
                        lambda i: small_frames[i].astype(np.int16),
                        len(small_frames),
                    )
                except Exception as exc:
                    self.output_queue.put(f"[Detect warning] {exc}\n")

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
                    },
                )
            )
        finally:
            for clone_frame in cloned_frames:
                cam.IMV_ReleaseFrame(clone_frame)

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

    # ------------------------------------------------------------------
    # Injection extraction
    # ------------------------------------------------------------------
    def _find_injection(self, source=None):
        if self.extract_thread and self.extract_thread.is_alive():
            return

        try:
            before = int(self.before_var.get())
            after = int(self.after_var.get())
            if before < 0 or after < 0:
                raise ValueError
        except ValueError:
            self.status_var.set("Frames before/after must be >= 0 integers.")
            return

        # Manual button click (source is None): always let the user pick the
        # burst folder. The post-capture auto-chain passes the folder in.
        if source is None:
            initial = self.last_output_dir or self.output_dir_var.get() or str(ROOT)
            picked = filedialog.askdirectory(
                title="Select the burst folder to analyze",
                initialdir=str(initial),
            )
            if not picked:
                return
            source = Path(picked)
        else:
            source = Path(source)

        self._append_log(f"Analyzing {source} for the injection event...\n")
        self.status_var.set("Finding injection...")
        self.extract_button.configure(state=tk.DISABLED)

        self.extract_thread = threading.Thread(
            target=self._extract_worker,
            args=(Path(source), before, after),
            daemon=True,
        )
        self.extract_thread.start()

    def _auto_copy_injection(self, info):
        """Copy the injection window using bounds already detected in RAM."""
        if self.extract_thread and self.extract_thread.is_alive():
            return
        self._append_log("Finding injection (in-memory, no disk re-read)...\n")
        self.status_var.set("Finding injection...")
        self.extract_button.configure(state=tk.DISABLED)
        self.extract_thread = threading.Thread(
            target=self._copy_injection_worker,
            args=(info,),
            daemon=True,
        )
        self.extract_thread.start()

    def _copy_injection_worker(self, info):
        try:
            bounds = info.get("bounds")
            signal = info["signal"]
            if bounds is None:
                bounds = injection_extract.detect_injection_bounds(
                    np.asarray(signal, dtype=np.float64)
                )
            if bounds is None:
                raise RuntimeError(
                    "No injection detected. The motion in this burst is too "
                    "small (no clear high-pressure jet event)."
                )
            start, end, peak = bounds
            result = injection_extract.build_result(
                info["files"], signal, "in-memory (capture)",
                start, end, peak,
                source_dir=info["dir"], dest_base=INJECTION_DIR,
                before=info.get("before", 30), after=info.get("after", 30),
                copy=True,
            )
            self.output_queue.put(("EXTRACT_DONE", result))
        except Exception as exc:
            self.output_queue.put(("EXTRACT_ERROR", str(exc)))

    def _auto_extract_from_signal(self, files, signal):
        """Fallback: detect from the in-RAM signal (temporal only) and copy."""
        self._auto_copy_injection(
            {
                "files": files,
                "signal": signal,
                "bounds": None,
                "dir": str(Path(files[0]).parent) if files else "",
                "before": self.capture_params.before if self.capture_params else 30,
                "after": self.capture_params.after if self.capture_params else 30,
            }
        )

    def _extract_worker(self, source, before, after):
        last = [0]

        def progress(done, total):
            pct = int(done * 100 / total) if total else 0
            if pct != last[0]:
                last[0] = pct
                self.output_queue.put(("STATUS", f"Finding injection... {pct}%"))

        try:
            result = injection_extract.extract_injection(
                source,
                dest_base=INJECTION_DIR,
                before=before,
                after=after,
                progress=progress,
            )
            self.output_queue.put(("EXTRACT_DONE", result))
        except Exception as exc:
            self.output_queue.put(("EXTRACT_ERROR", str(exc)))

    def _on_extract_done(self, result):
        self.extract_button.configure(state=tk.NORMAL)
        self._append_log(
            "Injection detected.\n"
            f"  Method:            {result.get('method', '?')}\n"
            f"  Peak frame:        {result['peak_frame']}\n"
            f"  Injection frames:  {result['injection_start_frame']} .. "
            f"{result['injection_end_frame']} ({result['injection_count']})\n"
            f"  Copied window:     {result['copy_start_frame']} .. "
            f"{result['copy_end_frame']} "
            f"({result['before']} before, {result['after']} after)\n"
            f"  Saved {result['selected_count']} images to:\n"
            f"  {result['dest_dir']}\n"
        )
        self.status_var.set(
            f"Injection: saved {result['selected_count']} images."
        )
        # Point "Open Last Folder" / "Measure" at the freshly extracted images.
        self.last_output_dir = Path(result["dest_dir"])
        self.last_injection_dir = Path(result["dest_dir"])

        # Chain when this extraction was triggered by a capture:
        # find injection -> make slow-motion video -> measure. The video runs on
        # its own thread; measure is chained once it finishes (VIDEO_DONE), gated
        # by auto_measure_pending which stays set until then.
        if self.auto_measure_pending:
            self._make_video(self.last_injection_dir)

    # ------------------------------------------------------------------
    # Spray-angle measurement
    # ------------------------------------------------------------------
    def _line_frac(self):
        """Drawn-line length as a fraction of image width (from the left), or None (full)."""
        return {"Full": None, "3/4": 0.75, "2/3": 2.0 / 3.0, "1/2": 0.5}.get(
            self.line_len_var.get(), None
        )

    def _measure_injection(self, source=None):
        if self.measure_thread and self.measure_thread.is_alive():
            return

        # Manual button click (source is None): always let the user pick a
        # folder. Auto-chain after a capture passes the injection folder in.
        if source is None:
            initial = self.last_injection_dir or (
                INJECTION_DIR if INJECTION_DIR.exists() else ROOT
            )
            picked = filedialog.askdirectory(
                title="Select an injection-images folder to measure",
                initialdir=str(initial),
            )
            if not picked:
                return
            source = Path(picked)
        else:
            source = Path(source)

        try:
            start = int(self.measure_start_var.get())
            end = int(self.measure_end_var.get())
            if start < 1 or end < start:
                raise ValueError
        except ValueError:
            start, end = 10, 20

        self._append_log(
            f"Measuring spray angle in {source} (jet frames {start}-{end}) ...\n"
        )
        self.status_var.set("Measuring spray angle...")
        self.measure_button.configure(state=tk.DISABLED)
        self.measure_thread = threading.Thread(
            target=self._measure_worker,
            args=(Path(source), start, end, self._line_frac()),
            daemon=True,
        )
        self.measure_thread.start()

    def _measure_worker(self, source, start, end, line_frac):
        def progress(done, total):
            self.output_queue.put(("STATUS", f"Measuring... {done}/{total}"))

        try:
            result = measure_angle.measure_folder(
                source, dest_base=MEASURE_DIR, start=start, end=end,
                line_frac=line_frac, progress=progress,
            )
            self.output_queue.put(("MEASURE_DONE", result))
        except Exception as exc:
            self.output_queue.put(("MEASURE_ERROR", str(exc)))

    def _on_measure_done(self, result):
        self.measure_button.configure(state=tk.NORMAL)
        conf_by_name = {
            name: level for name, _, level in result.get("frame_confidence", [])
        }
        lines = "".join(
            f"    {name}: {angle:.2f} deg [{conf_by_name.get(name, '?')}]\n"
            for name, angle in result["frames"]
        )
        confidence = result.get("confidence", "?")
        self._append_log(
            "Spray angle measured.\n"
            f"  Frames measured: {result['measured_count']}\n"
            f"  Angle mean/min/max: {result['mean_angle']:.2f} / "
            f"{result['min_angle']:.2f} / {result['max_angle']:.2f} deg "
            f"(std {result.get('angle_std', 0.0):.3f})\n"
            f"  Trusted mean: {result.get('trusted_mean', result['mean_angle']):.2f} deg "
            f"({result.get('trusted_count', result['measured_count'])} frames, "
            f"Low-confidence excluded)\n"
            f"  Confidence: {confidence} ({result.get('run_quality', 0.0):.0f}/100)\n"
            f"{lines}"
            f"  Saved to: {result['dest_dir']}\n"
        )
        self.status_var.set(
            f"Measured {result['measured_count']} frames, "
            f"trusted mean {result.get('trusted_mean', result['mean_angle']):.2f} deg, "
            f"confidence {confidence}."
        )
        self.last_output_dir = Path(result["dest_dir"])

    # ------------------------------------------------------------------
    # Angle-block measurement (single still)
    # ------------------------------------------------------------------
    def _measure_block(self):
        if (self.block_thread and self.block_thread.is_alive()) or self.block_requested.is_set():
            return
        # Need the camera open/grabbing to take the still.
        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()
        self._block_line_frac = self._line_frac()
        self._append_log("Capturing angle-block still...\n")
        self.status_var.set("Capturing angle block...")
        self.block_button.configure(state=tk.DISABLED)
        self.block_requested.set()

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

    def _grab_block_still(self, cam, sdk):
        """Grab one frame of the angle block and hand its path to the GUI."""
        self._grab_still(cam, sdk, "block", "BLOCK_CAPTURED", BLOCK_DIR)

    def _block_worker(self, path):
        try:
            # Bright block on dark background -> bright region is the foreground.
            result = measure_block.measure_block_image(
                path, dest_base=MEASURE_DIR, invert=False, line_frac=self._block_line_frac
            )
            self.output_queue.put(("BLOCK_DONE", result))
        except Exception as exc:
            self.output_queue.put(("BLOCK_ERROR", str(exc)))

    def _on_block_done(self, result):
        self.block_button.configure(state=tk.NORMAL)
        self._append_log(
            "Angle block measured.\n"
            f"  Angle:       {result['angle']:.2f} deg\n"
            f"  Edge slopes: upper {result['k_upper']:.4f}, lower {result['k_lower']:.4f}\n"
            f"  Edge points: {result['n_points']}\n"
            f"  Saved to:    {result['out_path']}\n"
        )
        self.status_var.set(f"Angle block: {result['angle']:.2f} deg")
        self.last_output_dir = Path(result["out_path"]).parent

    # ------------------------------------------------------------------
    # Slow-motion video from injection images
    # ------------------------------------------------------------------
    def _make_video(self, source=None):
        if self.video_thread and self.video_thread.is_alive():
            return

        # Default to the last extracted injection folder; otherwise let the user
        # pick one from the "injection images" directory.
        if source is None:
            initial = self.last_injection_dir or (
                INJECTION_DIR if INJECTION_DIR.exists() else ROOT
            )
            picked = filedialog.askdirectory(
                title="Select an injection-images folder to build a slow-motion video",
                initialdir=str(initial),
            )
            if not picked:
                return
            source = Path(picked)
        else:
            source = Path(source)

        self._append_log(f"Building slow-motion video from {source} ...\n")
        self.status_var.set("Making slow-motion video...")
        self.video_button.configure(state=tk.DISABLED)
        self.video_thread = threading.Thread(
            target=self._video_worker, args=(Path(source),), daemon=True
        )
        self.video_thread.start()

    def _video_worker(self, source):
        def progress(done, total):
            self.output_queue.put(("STATUS", f"Making video... {done}/{total}"))

        try:
            result = make_video.make_video(source, progress=progress)
            self.output_queue.put(("VIDEO_DONE", result))
        except Exception as exc:
            self.output_queue.put(("VIDEO_ERROR", str(exc)))

    def _on_video_done(self, result):
        self.video_button.configure(state=tk.NORMAL)
        w, h = result["size"]
        self._append_log(
            "Slow-motion video saved.\n"
            f"  Frames:   {result['frame_count']} @ {result['fps']} fps playback\n"
            f"  Size:     {w}x{h}\n"
            f"  Saved to: {result['out_path']}\n"
        )
        self.status_var.set(f"Video saved: {Path(result['out_path']).name}")
        self.last_output_dir = Path(result["out_path"]).parent
        self._maybe_auto_measure_after_video()

    def _maybe_auto_measure_after_video(self):
        """In the capture pipeline, measure the spray angle once the video is done.

        A no-op for manual "Make Video" clicks (auto_measure_pending is False).
        """
        if self.auto_measure_pending:
            self.auto_measure_pending = False
            self._measure_injection(self.last_injection_dir)

    # ------------------------------------------------------------------
    # Spatial calibration (mm per pixel from a reference block still)
    # ------------------------------------------------------------------
    def _calibrate_scale(self, auto=False):
        if self.scale_requested.is_set() or (self.scale_thread and self.scale_thread.is_alive()):
            return
        try:
            ref_mm = float(self.ref_mm_var.get())
            if ref_mm <= 0:
                raise ValueError
        except ValueError:
            self.status_var.set("Cal. distance must be a positive number (mm).")
            return
        self._scale_auto = auto
        # Need the camera open/grabbing to take the still.
        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()
        how = "auto-detecting" if auto else "manual ROI"
        self._append_log(f"Capturing scale-reference still ({ref_mm:g} mm, {how})...\n")
        self.status_var.set("Capturing scale reference...")
        self.scale_button.configure(state=tk.DISABLED)
        self.autoscale_button.configure(state=tk.DISABLED)
        self.scale_requested.set()

    def _on_scale_captured(self, path):
        """After the still is grabbed: auto-calibrate, or open the ROI dialog."""
        if self._scale_auto:
            try:
                ref_mm = float(self.ref_mm_var.get())
            except ValueError:
                ref_mm = 10.0
            self._append_log(
                f"Captured {path}\nAuto-detecting two dark lines (left third)...\n"
            )
            self.status_var.set("Auto-calibrating...")
            self.scale_thread = threading.Thread(
                target=self._autoscale_worker, args=(path, ref_mm), daemon=True
            )
            self.scale_thread.start()
        else:
            self._open_scale_dialog(path)

    def _autoscale_worker(self, path, ref_mm):
        try:
            record = calibrate_scale.auto_calibrate_image(path, ref_mm)
            self.output_queue.put(("SCALE_DONE", record))
        except Exception as exc:
            self.output_queue.put(("SCALE_ERROR", str(exc)))

    def _open_scale_dialog(self, path):
        """Open the ROI calibration dialog on the freshly captured still."""
        self.scale_button.configure(state=tk.NORMAL)
        self.autoscale_button.configure(state=tk.NORMAL)
        try:
            ref_mm = float(self.ref_mm_var.get())
        except ValueError:
            ref_mm = 10.0
        self._append_log(
            f"Captured {path}\n"
            "Draw an ROI around each reference edge, then click 'Detect Edge'.\n"
        )
        try:
            calibrate_ui.CalibrationDialog(
                self, path, ref_mm=ref_mm, on_saved=self._on_scale_saved
            )
        except Exception as exc:
            self.status_var.set(f"Scale: {exc}")
            self._append_log(f"[Scale Error] {exc}\n")

    def _on_scale_saved(self, record):
        self.scale_button.configure(state=tk.NORMAL)
        self.autoscale_button.configure(state=tk.NORMAL)
        self._append_log(
            "Scale calibrated.\n"
            f"  Edge gap:    {record['ref_mm']:g} mm = {record['gap_px']:.1f} px\n"
            f"  Scale:       {record['mm_per_px']:.5f} mm/px "
            f"({record['px_per_mm']:.2f} px/mm)\n"
            f"  Saved to:    {record.get('calibration_file', '?')}\n"
            f"  Check image: {record['annotated']}\n"
            "  Confirm the two green lines sit on the outer edge of each dark line.\n"
        )
        self.status_var.set(
            f"Scale: {record['mm_per_px']:.5f} mm/px "
            f"({record['px_per_mm']:.2f} px/mm)"
        )
        self.last_output_dir = Path(record["annotated"]).parent
        try:                                # show the check image for confirmation
            os.startfile(record["annotated"])
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Measure an unknown block's size (mm) using the stored calibration
    # ------------------------------------------------------------------
    def _measure_block_size(self):
        if self.measblock_requested.is_set() or (
            self.measblock_thread and self.measblock_thread.is_alive()):
            return
        if calibrate_scale.load_calibration() is None:
            self.status_var.set("No scale calibration yet - run Calibrate Scale first.")
            self._append_log("[Measure Block] No calibration found. Calibrate the "
                             "scale on a known block first.\n")
            return
        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()
        self._append_log("Capturing block still to measure...\n")
        self.status_var.set("Capturing block...")
        self.measblock_button.configure(state=tk.DISABLED)
        self.measblock_requested.set()

    def _measblock_worker(self, path):
        try:
            record = calibrate_scale.measure_block_size(path)
            self.output_queue.put(("MEASBLOCK_DONE", record))
        except Exception as exc:
            self.output_queue.put(("MEASBLOCK_ERROR", str(exc)))

    def _on_measblock_done(self, record):
        self.measblock_button.configure(state=tk.NORMAL)
        self._append_log(
            "Block measured.\n"
            f"  Size:        {record['mm']:.3f} mm\n"
            f"  Edge gap:    {record['gap_px']:.1f} px @ {record['mm_per_px']:.5f} mm/px\n"
            f"  (calibrated on a {record['calibration_ref_mm']:g} mm reference)\n"
            f"  Overlay:     {record['annotated']}\n"
        )
        self.status_var.set(f"Block size: {record['mm']:.3f} mm")
        self.last_output_dir = Path(record["annotated"]).parent
        try:
            os.startfile(record["annotated"])
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Nozzle reference lines (tip edge + centerline), auto-detected, reused
    # ------------------------------------------------------------------
    def _set_reference(self):
        if self.reference_requested.is_set():
            return
        # Capture a still of the nozzle (no jet), then detect the tip on it.
        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()
        self._append_log("Capturing nozzle still for reference lines...\n")
        self.status_var.set("Capturing nozzle...")
        self.reference_button.configure(state=tk.DISABLED)
        self.reference_requested.set()

    def _open_reference_dialog(self, path):
        """Open the mark-and-detect reference dialog on the captured nozzle still."""
        self.reference_button.configure(state=tk.NORMAL)
        self._append_log(
            f"Captured {path}\n"
            "Draw a box on the nozzle tip, then click 'Detect Edge'.\n"
        )
        try:
            reference_ui.ReferenceDialog(
                self, path, nozzle_side=1, on_saved=self._on_reference_done
            )
        except Exception as exc:
            self.status_var.set(f"Reference: {exc}")
            self._append_log(f"[Reference Error] {exc}\n")

    def _on_reference_done(self, ref):
        self.reference_button.configure(state=tk.NORMAL)
        self._append_log(
            "Nozzle reference set.\n"
            f"  Tip edge (red):    x={ref['nozzle_p0'][0]:.0f}, "
            f"y={ref['nozzle_p0'][1]:.0f}..{ref['nozzle_p1'][1]:.0f}\n"
            f"  Centerline (blue): y={ref['mid'][1]:.0f}\n"
            f"  Saved to:  {ref.get('reference_file', '?')}\n"
            f"  Check img: {ref['annotated']}\n"
            "  Now overlaid on measured frames. Re-set it if the nozzle/camera moves.\n"
        )
        self.status_var.set(f"Nozzle reference set (centerline y={ref['mid'][1]:.0f}).")
        self.last_output_dir = Path(ref["annotated"]).parent

    # ------------------------------------------------------------------
    # Queue draining
    # ------------------------------------------------------------------
    def _drain_output_queue(self):
        while True:
            try:
                item = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if isinstance(item, tuple):
                kind, payload = item
                if kind == "STATUS":
                    self.status_var.set(payload)
                elif kind == "CAPTURE_DONE":
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
                elif kind == "CAPTURE_ERROR":
                    self.status_var.set(f"Error: {payload}")
                    self._append_log(f"[Capture Error] {payload}\n")
                    self.run_button.configure(state=tk.NORMAL)
                    self.stop_button.configure(state=tk.DISABLED)
                elif kind == "EXTRACT_DONE":
                    self._on_extract_done(payload)
                elif kind == "EXTRACT_ERROR":
                    self.status_var.set(f"Injection: {payload}")
                    self._append_log(f"[Injection Error] {payload}\n")
                    self.extract_button.configure(state=tk.NORMAL)
                    self.auto_measure_pending = False
                elif kind == "MEASURE_DONE":
                    self._on_measure_done(payload)
                elif kind == "MEASURE_ERROR":
                    self.status_var.set(f"Measure: {payload}")
                    self._append_log(f"[Measure Error] {payload}\n")
                    self.measure_button.configure(state=tk.NORMAL)
                elif kind == "BLOCK_CAPTURED":
                    self._append_log(f"Captured {payload}\nMeasuring angle block...\n")
                    self.status_var.set("Measuring angle block...")
                    self.block_thread = threading.Thread(
                        target=self._block_worker, args=(payload,), daemon=True
                    )
                    self.block_thread.start()
                elif kind == "BLOCK_DONE":
                    self._on_block_done(payload)
                elif kind == "BLOCK_ERROR":
                    self.status_var.set(f"Angle block: {payload}")
                    self._append_log(f"[Angle Block Error] {payload}\n")
                    self.block_button.configure(state=tk.NORMAL)
                elif kind == "VIDEO_DONE":
                    self._on_video_done(payload)
                elif kind == "VIDEO_ERROR":
                    self.status_var.set(f"Video: {payload}")
                    self._append_log(f"[Video Error] {payload}\n")
                    self.video_button.configure(state=tk.NORMAL)
                    # Don't strand the capture pipeline if the video step fails.
                    self._maybe_auto_measure_after_video()
                elif kind == "SCALE_CAPTURED":
                    self._on_scale_captured(payload)
                elif kind == "SCALE_DONE":
                    self._on_scale_saved(payload)
                elif kind == "SCALE_ERROR":
                    self.status_var.set(f"Scale: {payload}")
                    self._append_log(f"[Scale Error] {payload}\n")
                    self.scale_button.configure(state=tk.NORMAL)
                    self.autoscale_button.configure(state=tk.NORMAL)
                elif kind == "MEASBLOCK_CAPTURED":
                    self._append_log(f"Captured {payload}\nMeasuring block size...\n")
                    self.status_var.set("Measuring block...")
                    self.measblock_thread = threading.Thread(
                        target=self._measblock_worker, args=(payload,), daemon=True
                    )
                    self.measblock_thread.start()
                elif kind == "MEASBLOCK_DONE":
                    self._on_measblock_done(payload)
                elif kind == "MEASBLOCK_ERROR":
                    self.status_var.set(f"Measure Block: {payload}")
                    self._append_log(f"[Measure Block Error] {payload}\n")
                    self.measblock_button.configure(state=tk.NORMAL)
                elif kind == "REFERENCE_CAPTURED":
                    self._open_reference_dialog(payload)
                elif kind == "REFERENCE_ERROR":
                    self.status_var.set(f"Reference: {payload}")
                    self._append_log(f"[Reference Error] {payload}\n")
                    self.reference_button.configure(state=tk.NORMAL)
                continue

            self._append_log(item)

        self.after(100, self._drain_output_queue)

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

    def _open_last_folder(self):
        folder = self.last_output_dir or Path(self.output_dir_var.get())
        if folder.exists():
            os.startfile(folder)
        else:
            self.status_var.set("No output folder found yet.")

    def _on_close(self):
        """Clean up resources when the window is closed."""
        try:
            self.preview_stop.set()
            self.capture_abort.set()
            if self.camera_thread and self.camera_thread.is_alive():
                self.camera_thread.join(timeout=2)
        except Exception as exc:
            print(f"Close error: {exc}")

        self.destroy()


def _run_selftest(folder):
    """Headless check that a packaged build works without a camera.

    Runs the measure pipeline (cv2 / scipy / scikit-learn) and the slow-motion
    video build on an existing injection-images folder, writing the outcome to
    ``selftest.log`` next to the app (a windowed build has no console). Returns a
    process exit code (0 = passed).
    """
    import traceback

    log_path = data_root() / "selftest.log"
    lines = [f"Self-test on: {folder}"]
    code = 0
    try:
        res = measure_angle.measure_folder(
            folder, dest_base=data_root() / "selftest_out"
        )
        lines.append(
            f"MEASURE OK: {res['measured_count']} frames, "
            f"mean {res['mean_angle']:.3f} deg -> {res['dest_dir']}"
        )
        vid = make_video.make_video(folder)
        lines.append(f"VIDEO OK: {vid['frame_count']} frames -> {vid['out_path']}")
        lines.append("SELFTEST PASSED")
    except Exception:
        lines.append("SELFTEST FAILED:")
        lines.append(traceback.format_exc())
        code = 1

    text = "\n".join(lines)
    try:
        log_path.write_text(text, encoding="utf-8")
    except Exception:
        pass
    print(text)
    return code


def main(argv=None):
    """GUI entry point; ``--selftest <injection folder>`` runs headless."""
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 2 and argv[0] == "--selftest":
        return _run_selftest(argv[1])

    app = CaptureGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
