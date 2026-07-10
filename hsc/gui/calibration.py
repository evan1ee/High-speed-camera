#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Calibrate Scale / Auto Calibrate / Measure Block: spatial calibration
(mm per pixel) from a reference-block still, and measuring an unknown block
against the stored calibration."""

import os
import threading
import tkinter as tk
from pathlib import Path

from hsc import calibrate_scale
from hsc import calibrate_ui
from hsc.gui.config import SCALE_DIR


class CalibrationMixin:
    """Scale calibration + block-size measurement actions and handlers."""

    QUEUE_HANDLERS = {
        "SCALE_CAPTURED": "_on_scale_captured",
        "SCALE_DONE": "_on_scale_saved",
        "SCALE_ERROR": "_on_scale_error",
        "MEASBLOCK_CAPTURED": "_on_measblock_captured",
        "MEASBLOCK_DONE": "_on_measblock_done",
        "MEASBLOCK_ERROR": "_on_measblock_error",
    }

    def _init_calibration_state(self):
        self.scale_requested = threading.Event()
        self.scale_thread = None
        self._scale_auto = False
        self.measblock_requested = threading.Event()
        self.measblock_thread = None

        self.ref_mm_var = tk.StringVar(value="10")

        self.register_still_request(
            self.scale_requested, "scale", "SCALE_CAPTURED", "SCALE_ERROR",
            SCALE_DIR, buttons=("scale_button", "autoscale_button"),
        )
        self.register_still_request(
            self.measblock_requested, "measblock", "MEASBLOCK_CAPTURED",
            "MEASBLOCK_ERROR", SCALE_DIR, buttons=("measblock_button",),
        )

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
                f"Captured {path}\nAuto-detecting the two block edges (left third)...\n"
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

    def _on_scale_error(self, payload):
        self.status_var.set(f"Scale: {payload}")
        self._append_log(f"[Scale Error] {payload}\n")
        self.scale_button.configure(state=tk.NORMAL)
        self.autoscale_button.configure(state=tk.NORMAL)

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

    def _on_measblock_captured(self, payload):
        self._append_log(f"Captured {payload}\nMeasuring block size...\n")
        self.status_var.set("Measuring block...")
        self.measblock_thread = threading.Thread(
            target=self._measblock_worker, args=(payload,), daemon=True
        )
        self.measblock_thread.start()

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

    def _on_measblock_error(self, payload):
        self.status_var.set(f"Measure Block: {payload}")
        self._append_log(f"[Measure Block Error] {payload}\n")
        self.measblock_button.configure(state=tk.NORMAL)
