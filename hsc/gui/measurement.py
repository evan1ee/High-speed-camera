#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Measure: spray-angle measurement of an injection folder, and the
angle-block single-still measurement used to verify the pipeline."""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from hsc import measure_angle
from hsc import measure_block
from hsc.gui.config import BLOCK_DIR, INJECTION_DIR, MEASURE_DIR, ROOT


class MeasurementMixin:
    """Spray-angle + angle-block measurement actions and queue handlers."""

    QUEUE_HANDLERS = {
        "MEASURE_DONE": "_on_measure_done",
        "MEASURE_ERROR": "_on_measure_error",
        "BLOCK_CAPTURED": "_on_block_captured",
        "BLOCK_DONE": "_on_block_done",
        "BLOCK_ERROR": "_on_block_error",
    }

    def _init_measurement_state(self):
        self.measure_thread = None
        self.block_thread = None
        self.block_requested = threading.Event()
        self._block_line_frac = None

        self.measure_start_var = tk.StringVar(value="10")
        self.measure_end_var = tk.StringVar(value="20")
        self.line_len_var = tk.StringVar(value="Full")

        self.register_still_request(
            self.block_requested, "block", "BLOCK_CAPTURED", "BLOCK_ERROR",
            BLOCK_DIR, buttons=("block_button",),
        )

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

    def _on_measure_error(self, payload):
        self.status_var.set(f"Measure: {payload}")
        self._append_log(f"[Measure Error] {payload}\n")
        self.measure_button.configure(state=tk.NORMAL)

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

    def _block_worker(self, path):
        try:
            # Bright block on dark background -> bright region is the foreground.
            result = measure_block.measure_block_image(
                path, dest_base=MEASURE_DIR, invert=False, line_frac=self._block_line_frac
            )
            self.output_queue.put(("BLOCK_DONE", result))
        except Exception as exc:
            self.output_queue.put(("BLOCK_ERROR", str(exc)))

    def _on_block_captured(self, payload):
        self._append_log(f"Captured {payload}\nMeasuring angle block...\n")
        self.status_var.set("Measuring angle block...")
        self.block_thread = threading.Thread(
            target=self._block_worker, args=(payload,), daemon=True
        )
        self.block_thread.start()

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

    def _on_block_error(self, payload):
        self.status_var.set(f"Angle block: {payload}")
        self._append_log(f"[Angle Block Error] {payload}\n")
        self.block_button.configure(state=tk.NORMAL)
