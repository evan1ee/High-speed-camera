#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Find Injection: extract the injection window from a burst, either from the
in-memory capture data (auto-chain) or by re-scanning a folder on disk."""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import numpy as np

from hsc import injection_extract
from hsc.gui.config import INJECTION_DIR, ROOT


class ExtractionMixin:
    """Injection extraction actions + queue handlers."""

    QUEUE_HANDLERS = {
        "EXTRACT_DONE": "_on_extract_done",
        "EXTRACT_ERROR": "_on_extract_error",
    }

    def _init_extraction_state(self):
        self.extract_thread = None

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
        # find injection -> measure -> make slow-motion video. Measure runs on
        # its own thread; the video is chained once it finishes (MEASURE_DONE),
        # gated by auto_measure_pending which stays set until then.
        if self.auto_measure_pending:
            self._measure_injection(self.last_injection_dir)

    def _on_extract_error(self, payload):
        self.status_var.set(f"Injection: {payload}")
        self._append_log(f"[Injection Error] {payload}\n")
        self.extract_button.configure(state=tk.NORMAL)
        self.auto_measure_pending = False
        self._pipeline_t0 = None
