#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Measure: spray-angle measurement of an injection folder, and the
angle-block single-still measurement used to verify the pipeline."""

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from hsc import measure_angle
from hsc import measure_block
from hsc.gui.config import BLOCK_DIR, INJECTION_DIR, MEASURE_DIR, ROOT


def _format_frame_lines(result):
    """Per-frame log lines: name, angle, confidence and -- when a reference
    rectangle exists -- the jet-inside-rectangle verdict (``, OK``/``, NG``)."""
    conf_by_name = {
        name: level for name, _, level in result.get("frame_confidence", [])
    }
    rect_by_name = dict(result.get("frame_in_rect", []))
    lines = []
    for name, angle in result["frames"]:
        verdict = rect_by_name.get(name, "")
        suffix = f", {verdict}" if verdict else ""
        lines.append(
            f"    {name}: {angle:.2f} deg "
            f"[{conf_by_name.get(name, '?')}]{suffix}\n")
    return "".join(lines)


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
        # Auto pick: ignore from/to and measure the first run of 5 consecutive
        # stable jet frames after the injection starts (find_stable_window).
        self.auto_pick_var = tk.BooleanVar(value=False)
        self.line_len_var = tk.StringVar(value="Full")
        # A/B switch: measure with the benchmark-gated V2 edge-detection set
        # (erf edge model + pre-onset background + trusted-edge policy).
        # Off = the unchanged legacy pipeline.
        self.edge_v2_var = tk.BooleanVar(value=False)
        # Draw the yellow tip line + blue centerline on measure output images
        # (the red rectangle is always drawn when a reference is set).
        self.ref_lines_var = tk.BooleanVar(value=True)

        self.register_still_request(
            self.block_requested, "block", "BLOCK_CAPTURED", "BLOCK_ERROR",
            BLOCK_DIR, buttons=("block_button",),
        )

    # ------------------------------------------------------------------
    # Spray-angle measurement
    # ------------------------------------------------------------------
    def _toggle_auto_pick(self):
        """Grey out the Measure from/to entries while auto pick is on."""
        state = tk.DISABLED if self.auto_pick_var.get() else tk.NORMAL
        for entry in (self.measure_start_entry, self.measure_end_entry):
            entry.configure(state=state)

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
            self._pipeline_t0 = None       # manual run: no capture total
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

        auto_pick = bool(self.auto_pick_var.get())
        use_v2 = bool(self.edge_v2_var.get())
        edition = "V2 (erf + pre-onset bg + trusted policy)" if use_v2 else "V1 (legacy)"
        frames_note = (
            f"auto pick: first {measure_angle.AUTO_PICK_COUNT} consecutive stable frames"
            if auto_pick else f"jet frames {start}-{end}"
        )
        self._append_log(
            f"Measuring spray angle in {source} ({frames_note}, "
            f"edge detection {edition}) ...\n"
        )
        self.status_var.set("Measuring spray angle...")
        self.measure_button.configure(state=tk.DISABLED)
        self.measure_thread = threading.Thread(
            target=self._measure_worker,
            args=(Path(source), start, end, self._line_frac(), use_v2, auto_pick,
                  bool(self.ref_lines_var.get())),
            daemon=True,
        )
        self.measure_thread.start()

    def _measure_worker(self, source, start, end, line_frac, use_v2=False,
                        auto_pick=False, ref_lines=True):
        def progress(done, total):
            self.output_queue.put(("STATUS", f"Measuring... {done}/{total}"))

        try:
            with measure_angle.edge_v2(use_v2):
                result = measure_angle.measure_folder(
                    source, dest_base=MEASURE_DIR, start=start, end=end,
                    line_frac=line_frac, progress=progress, auto_pick=auto_pick,
                    ref_lines=ref_lines,
                )
            self.output_queue.put(("MEASURE_DONE", result))
        except Exception as exc:
            self.output_queue.put(("MEASURE_ERROR", str(exc)))

    def _on_measure_done(self, result):
        self.measure_button.configure(state=tk.NORMAL)
        lines = _format_frame_lines(result)
        confidence = result.get("confidence", "?")
        model = result.get("edge_model", "legacy")
        edition = "V1 (legacy)" if model == "legacy" else (
            f"V2 ({model}/{result.get('bg_mode', '?')}/"
            f"{result.get('angle_policy_mode', '?')})"
        )
        pooled = result.get("pooled_angle")
        pooled_line = (
            f"  Pooled angle: {pooled:.2f} deg "
            f"({result.get('pooled_n', 0)} edge samples, all-frame fit)\n"
            if pooled is not None and pooled == pooled else ""
        )
        auto_line = ""
        if result.get("auto_pick"):
            fallback = (" (no fully stable window found -- used the steadiest run)"
                        if result.get("auto_pick_fallback") else "")
            auto_line = f"  Auto pick: consecutive stable frames{fallback}\n"
        self._append_log(
            f"Spray angle measured with edge detection {edition}.\n"
            f"{auto_line}"
            f"  Frames measured: {result['measured_count']}\n"
            f"  Angle mean/min/max: {result['mean_angle']:.2f} / "
            f"{result['min_angle']:.2f} / {result['max_angle']:.2f} deg "
            f"(std {result.get('angle_std', 0.0):.3f})\n"
            f"  Trusted mean: {result.get('trusted_mean', result['mean_angle']):.2f} deg "
            f"({result.get('trusted_count', result['measured_count'])} frames, "
            f"Low-confidence excluded)\n"
            f"  Confidence: {confidence} ({result.get('run_quality', 0.0):.0f}/100)\n"
            f"{pooled_line}"
            f"{lines}"
            f"  Saved to: {result['dest_dir']}\n"
        )
        self.status_var.set(
            f"Measured {result['measured_count']} frames, "
            f"trusted mean {result.get('trusted_mean', result['mean_angle']):.2f} deg, "
            f"confidence {confidence}."
        )
        self.last_output_dir = Path(result["dest_dir"])
        # End of the timed find-injection -> measure pipeline: report the
        # total wall time so different settings can be compared.
        if self._pipeline_t0 is not None:
            total = time.perf_counter() - self._pipeline_t0
            self._pipeline_t0 = None
            self._append_log(
                f"Total time (find injection -> measurement finished): "
                f"{total:.1f}s\n"
            )
        # Auto chain: the slow-motion video is made AFTER measurement (it is
        # the slowest step and not part of the timed pipeline).
        self._maybe_auto_video_after_measure()

    def _on_measure_error(self, payload):
        self.status_var.set(f"Measure: {payload}")
        self._append_log(f"[Measure Error] {payload}\n")
        self.measure_button.configure(state=tk.NORMAL)
        self._pipeline_t0 = None
        # Still make the video so a failed measurement doesn't cost the run
        # its slow-motion record.
        self._maybe_auto_video_after_measure()

    def _maybe_auto_video_after_measure(self):
        """In the capture pipeline, make the slow-motion video once
        measurement is done. A no-op for manual Measure clicks
        (auto_measure_pending is False). Monitor-mode events skip the video
        (not wanted there) and pump the next queued event instead."""
        if not self.auto_measure_pending:
            return
        self.auto_measure_pending = False
        if self._monitor_chain_active:
            self._monitor_chain_active = False
            self._pump_monitor_chain()
            return
        self._make_video(self.last_injection_dir)

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
