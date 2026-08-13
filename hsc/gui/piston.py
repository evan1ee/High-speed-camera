#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Piston speed measurement: capture, find the stroke, measure it.

The three steps mirror the spray pipeline but track the nozzle **piston**
(a dark body travelling down a bright barrel) instead of the water jet:

* **Capture Piston** (Operation) -- a fixed-length burst that keeps every frame
  and records the per-frame camera timestamps needed for a speed axis. The
  camera side is :meth:`hsc.gui.camera_worker.CameraWorkerMixin._do_piston_capture`.
* **Find Injection Piston** (Workflow) -- locates the stroke from the piston's
  own displacement (not the jet's motion signal) and copies the padded window
  into ``data\\injection images\\``.
* **Measure Piston** (Workflow) -- per-frame green edge line, distance from the
  stroke-start frame, CSV, and the distance/speed curves.

After a capture the three chain automatically (no slow-motion video); each
button also works standalone on a folder the operator picks.
"""

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from types import SimpleNamespace

from hsc import capture_image
from hsc import measure_piston
from hsc import piston_track
from hsc.gui.config import (INJECTION_DIR, MEASURE_DIR, PAD_AFTER, PAD_BEFORE,
                            ROOT)


def _positive_or(text, fallback):
    """A positive number from an entry field, else *fallback*."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


class PistonMixin:
    """Piston capture / find / measure actions and their queue handlers."""

    QUEUE_HANDLERS = {
        "PISTON_CAPTURE_DONE": "_on_piston_capture_done",
        "PISTON_CAPTURE_ERROR": "_on_piston_capture_error",
        "PFIND_DONE": "_on_piston_find_done",
        "PFIND_ERROR": "_on_piston_find_error",
        "PMEASURE_DONE": "_on_piston_measure_done",
        "PMEASURE_ERROR": "_on_piston_measure_error",
    }

    def _init_piston_state(self):
        self.piston_requested = threading.Event()
        self.piston_abort = threading.Event()
        self.piston_params = None
        self.piston_find_thread = None
        self.piston_measure_thread = None
        # Set while a capture-triggered run is flowing through find -> measure.
        self.piston_chain = False
        self.last_piston_dir = None
        # Fallback frame rate for folders with no recorded timing (e.g. copied
        # by hand). Blank = use the timestamps written by Capture Piston.
        self.piston_fps_var = tk.StringVar(value="")
        # Find Injection Piston V2: locate the stroke with the parallel scan
        # instead of a full per-frame fit. Same window, ~20x faster.
        self.piston_v2_var = tk.BooleanVar(value=False)
        # Injector geometry -> jet speed and pressure by volume conservation
        # (see measure_piston.jet_from_piston). Properties of the device under
        # test, so they belong on screen rather than in a constant.
        self.barrel_mm_var = tk.StringVar(
            value=str(measure_piston.BARREL_DIAMETER_MM))
        self.orifice_mm_var = tk.StringVar(
            value=str(measure_piston.ORIFICE_DIAMETER_MM))

    # ------------------------------------------------------------------
    # Capture Piston (toggles to "Stop Piston" while the burst runs)
    # ------------------------------------------------------------------
    def _capture_piston(self):
        if self.piston_requested.is_set():
            self.piston_abort.set()
            self.status_var.set("Stopping piston capture...")
            return
        if self.capture_requested.is_set() or self.monitor_active:
            self.status_var.set("Finish the running capture first.")
            return

        try:
            duration, _, _ = self._validate_inputs()
        except ValueError as exc:
            self.status_var.set(str(exc))
            return

        base = self._build_capture_params()
        # The ROI comes from the Capture Settings selector. Cropping does not
        # change mm/px (that is optics, not sensor rows), so the stored
        # calibration stays valid at any of them -- but the worker still
        # rejects the burst if the camera delivers a size other than the one
        # asked for, which is the failure that WOULD corrupt the scale.
        aspect = self.aspect_var.get()
        width, height = capture_image.ASPECT_PRESETS[aspect]
        _, exposure, _ = self._validate_inputs()
        self.piston_params = SimpleNamespace(
            duration=duration,
            aspect=aspect,
            width=width,
            height=height,
            # Re-programmed onto the camera before the burst (see
            # camera_worker._do_piston_capture): the preview may have left it
            # on another ROI, and the sensor keeps the frame period of
            # whatever was last programmed.
            pixel_format="Mono8",
            center_roi=True,
            offset_x=None,
            offset_y=None,
            exposure_us=exposure,
            frame_rate=None,
            ext=base.ext,
            prefix=base.prefix,
            burst_dir=base.burst_dir,
            label=base.label,
        )
        self.last_output_dir = None
        self.log_text.delete("1.0", tk.END)
        self.piston_button.configure(text="Stop Piston")
        self.piston_chain = True

        # The worker picks the request up on its next loop iteration, so the
        # camera must already be open and grabbing (same pattern as Capture).
        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()

        self.piston_abort.clear()
        self.piston_requested.set()
        self.status_var.set("Capturing piston...")

    def _on_piston_capture_done(self, info):
        self._reset_piston_ui()
        self.last_output_dir = Path(info["dir"])
        self.status_var.set(f"Piston: captured {info['frames']} frames.")
        if self.piston_chain:
            self._find_piston_injection(info["dir"])

    def _on_piston_capture_error(self, payload):
        self._reset_piston_ui()
        self.piston_chain = False
        self.status_var.set(f"Piston capture: {payload}")
        self._append_log(f"[Piston Capture Error] {payload}\n")

    def _reset_piston_ui(self):
        """Return the Capture Piston toggle to idle. Idempotent; also called
        when the camera thread stops for any reason."""
        self.piston_requested.clear()
        self.piston_abort.clear()
        self.piston_button.configure(text="Capture Piston", state=tk.NORMAL)

    # ------------------------------------------------------------------
    # Find Injection Piston
    # ------------------------------------------------------------------
    def _find_piston_injection(self, source=None):
        if self.piston_find_thread and self.piston_find_thread.is_alive():
            return

        if source is None:
            self.piston_chain = False        # manual click: no capture chain
            initial = self.last_output_dir or self.output_dir_var.get() or str(ROOT)
            picked = filedialog.askdirectory(
                title="Select the piston burst folder to analyze",
                initialdir=str(initial),
            )
            if not picked:
                return
            source = Path(picked)
        else:
            source = Path(source)

        fast = bool(self.piston_v2_var.get())
        self._append_log(
            f"Analyzing {source} for the piston stroke"
            f"{' (V2 parallel scan)' if fast else ''}...\n")
        self.status_var.set("Finding piston stroke...")
        self.piston_find_button.configure(state=tk.DISABLED)
        self.piston_find_thread = threading.Thread(
            target=self._piston_find_worker, args=(source, fast), daemon=True)
        self.piston_find_thread.start()

    def _piston_find_worker(self, source, fast=False):
        last = [0]

        def progress(done, total):
            pct = int(done * 100 / total) if total else 0
            if pct != last[0]:
                last[0] = pct
                self.output_queue.put(
                    ("STATUS", f"Finding piston stroke... {pct}%"))

        try:
            started = time.perf_counter()
            result = piston_track.extract_piston_event(
                source, dest_base=INJECTION_DIR,
                before=PAD_BEFORE, after=PAD_AFTER, progress=progress,
                fast=fast)
            result["elapsed_s"] = time.perf_counter() - started
            result["scan"] = "V2 (parallel scan)" if fast else "V1 (full fit)"
            self.output_queue.put(("PFIND_DONE", result))
        except Exception as exc:
            self.output_queue.put(("PFIND_ERROR", str(exc)))

    def _on_piston_find_done(self, result):
        self.piston_find_button.configure(state=tk.NORMAL)
        self._append_log(
            "Piston stroke detected.\n"
            f"  Moving frames:   {result['move_start_frame']} .. "
            f"{result['move_end_frame']} ({result['move_count']})\n"
            f"  Copied window:   {result['copy_start_frame']} .. "
            f"{result['copy_end_frame']} "
            f"({result['before']} before, {result['after']} after)\n"
            f"  Travel:          {result['stroke_px']:.1f} px\n"
            f"  Scan:            {result.get('scan', 'V1 (full fit)')} in "
            f"{result.get('elapsed_s', float('nan')):.1f}s\n"
            f"  Saved {result['selected_count']} images to:\n"
            f"  {result['dest_dir']}\n"
        )
        self.status_var.set(
            f"Piston stroke: saved {result['selected_count']} images.")
        self.last_output_dir = Path(result["dest_dir"])
        self.last_piston_dir = Path(result["dest_dir"])
        if self.piston_chain:
            self._measure_piston(self.last_piston_dir)

    def _on_piston_find_error(self, payload):
        self.piston_find_button.configure(state=tk.NORMAL)
        self.piston_chain = False
        self.status_var.set(f"Piston stroke: {payload}")
        self._append_log(f"[Piston Stroke Error] {payload}\n")

    # ------------------------------------------------------------------
    # Measure Piston
    # ------------------------------------------------------------------
    def _measure_piston(self, source=None):
        if self.piston_measure_thread and self.piston_measure_thread.is_alive():
            return

        if source is None:
            self.piston_chain = False
            initial = self.last_piston_dir or (
                INJECTION_DIR if INJECTION_DIR.exists() else ROOT)
            picked = filedialog.askdirectory(
                title="Select a piston injection-images folder to measure",
                initialdir=str(initial),
            )
            if not picked:
                return
            source = Path(picked)
        else:
            source = Path(source)

        fps = self._piston_fps()
        note = f", {fps:.0f} fps (entered)" if fps else ""
        barrel = _positive_or(self.barrel_mm_var.get(),
                              measure_piston.BARREL_DIAMETER_MM)
        orifice = _positive_or(self.orifice_mm_var.get(),
                               measure_piston.ORIFICE_DIAMETER_MM)
        self._append_log(
            f"Measuring piston travel in {source}{note} "
            f"(barrel {barrel} mm, orifice {orifice} mm) ...\n")
        self.status_var.set("Measuring piston travel...")
        self.piston_measure_button.configure(state=tk.DISABLED)
        self.piston_measure_thread = threading.Thread(
            target=self._piston_measure_worker,
            args=(source, fps, barrel, orifice), daemon=True)
        self.piston_measure_thread.start()

    def _piston_fps(self):
        """The operator's fallback frame rate, or None when the field is blank."""
        try:
            fps = float(self.piston_fps_var.get())
        except (TypeError, ValueError):
            return None
        return fps if fps > 0 else None

    def _piston_measure_worker(self, source, fps, barrel_mm, orifice_mm):
        def progress(done, total):
            self.output_queue.put(("STATUS", f"Measuring piston... {done}/{total}"))

        try:
            result = measure_piston.measure_folder(
                source, dest_base=MEASURE_DIR, fps=fps, progress=progress,
                barrel_mm=barrel_mm, orifice_mm=orifice_mm,
                log=lambda message: self.output_queue.put(
                    f"[Piston note] {message}\n"))
            self.output_queue.put(("PMEASURE_DONE", result))
        except Exception as exc:
            self.output_queue.put(("PMEASURE_ERROR", str(exc)))

    def _on_piston_measure_done(self, result):
        self.piston_measure_button.configure(state=tk.NORMAL)
        self.piston_chain = False
        scale = (f"{result['mm_per_px']:.5f} mm/px ({result['scale_source']})"
                 if result["mm_per_px"] > 0 else "no calibration (pixels only)")
        if result["mm_per_px"] > 0:
            travel = (f"  Stroke:      {result['stroke_mm']:.3f} mm "
                      f"({result['stroke_px']:.1f} px)\n"
                      f"  Mean speed:  {result['mean_speed_mm_s']:.1f} mm/s "
                      f"({result['mean_speed_mm_s'] / 1000.0:.3f} m/s)\n"
                      f"  Peak speed:  {result['peak_speed_mm_s']:.1f} mm/s\n")
        else:
            travel = f"  Stroke:      {result['stroke_px']:.1f} px\n"
        self._append_log(
            "Piston travel measured.\n"
            f"  Frames:      {result['measured_count']} "
            f"({result['missing_count']} without an edge)\n"
            f"{travel}"
            f"  Duration:    {result['duration_ms']:.1f} ms "
            f"({result['move_start_frame']} .. {result['move_end_frame']})\n"
            f"  Jet (peak):  {result['peak_jet_speed_m_s']:.1f} m/s, "
            f"{result['peak_jet_pressure_MPa']:.2f} MPa "
            f"(area ratio {result['area_ratio']:.0f}x)\n"
            f"  Time base:   {result['timebase']} at {result['fps']:.1f} fps\n"
            f"  Scale:       {scale}\n"
            f"  Saved to:    {result['dest_dir']}\n"
        )
        if result["mm_per_px"] > 0:
            self.status_var.set(
                f"Piston: {result['stroke_mm']:.2f} mm in "
                f"{result['duration_ms']:.0f} ms, peak "
                f"{result['peak_speed_mm_s']:.0f} mm/s.")
        else:
            self.status_var.set(
                f"Piston: {result['stroke_px']:.1f} px travel (not calibrated).")
        self.last_output_dir = Path(result["dest_dir"])

    def _on_piston_measure_error(self, payload):
        self.piston_measure_button.configure(state=tk.NORMAL)
        self.piston_chain = False
        self.status_var.set(f"Piston measure: {payload}")
        self._append_log(f"[Piston Measure Error] {payload}\n")
