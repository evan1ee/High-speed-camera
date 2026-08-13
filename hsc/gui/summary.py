#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Summary: descriptive statistics across several measured piston runs.

Tk has no native multi-folder chooser, so the button opens a list of the
measured runs (newest first) with extended selection -- which is closer to
what the operator wants anyway than picking folders one at a time, because it
only offers folders that actually hold a measured run.
"""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from hsc import summary as summary_lib
from hsc.gui.config import MEASURE_DIR


class RunPicker(tk.Toplevel):
    """Modal multi-select list of measured run folders."""

    def __init__(self, master, folders, title="Select runs to summarize"):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.resizable(True, True)
        self.selected = None

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=f"{len(folders)} measured run(s). "
                              "Ctrl/Shift-click to select several.").pack(
            anchor="w", pady=(0, 8))

        body = ttk.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(body, selectmode=tk.EXTENDED, width=54,
                                  height=min(18, max(6, len(folders))),
                                  activestyle="none", exportselection=False)
        bar = ttk.Scrollbar(body, orient=tk.VERTICAL,
                            command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        bar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._folders = list(folders)
        for folder in self._folders:
            self.listbox.insert(tk.END, folder.name)
        self.listbox.selection_set(0, tk.END)          # default: all of them

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(buttons, text="Select all",
                   command=lambda: self.listbox.selection_set(0, tk.END)
                   ).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=self._cancel
                   ).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Summarize", command=self._accept
                   ).pack(side=tk.RIGHT, padx=(0, 8))

        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.listbox.focus_set()

    def _accept(self):
        self.selected = [self._folders[i] for i in self.listbox.curselection()]
        self.destroy()

    def _cancel(self):
        self.selected = None
        self.destroy()


class SummaryMixin:
    """Summary button + queue handlers."""

    QUEUE_HANDLERS = {
        "SUMMARY_DONE": "_on_summary_done",
        "SUMMARY_ERROR": "_on_summary_error",
    }

    def _init_summary_state(self):
        self.summary_thread = None

    def _measured_runs(self):
        """Run folders under data\\measure that hold a measured piston run,
        newest first."""
        if not MEASURE_DIR.exists():
            return []
        folders = [p for p in MEASURE_DIR.iterdir()
                   if p.is_dir() and summary_lib.find_csv(p) is not None]
        return sorted(folders, key=lambda p: p.stat().st_mtime, reverse=True)

    def _summarize_runs(self):
        if self.summary_thread and self.summary_thread.is_alive():
            return
        folders = self._measured_runs()
        if not folders:
            self.status_var.set(
                "No measured piston runs found under data\\measure.")
            return

        picker = RunPicker(self, folders)
        picker.grab_set()
        self.wait_window(picker)
        chosen = picker.selected
        if not chosen:
            return

        self._append_log(f"Summarizing {len(chosen)} run(s)...\n")
        self.status_var.set("Summarizing...")
        self.summary_button.configure(state=tk.DISABLED)
        self.summary_thread = threading.Thread(
            target=self._summary_worker, args=(chosen,), daemon=True)
        self.summary_thread.start()

    def _summary_worker(self, folders):
        try:
            # Written to the measure ROOT, beside the runs it describes.
            result = summary_lib.summarize(folders, MEASURE_DIR)
            self.output_queue.put(("SUMMARY_DONE", result))
        except Exception as exc:
            self.output_queue.put(("SUMMARY_ERROR", str(exc)))

    def _on_summary_done(self, result):
        self.summary_button.configure(state=tk.NORMAL)
        lines = [f"Summary of {len(result['runs'])} run(s).\n"]
        for name, reason in result["skipped"]:
            lines.append(f"  [skipped] {name}: {reason}\n")
        lines.append(f"  {'metric':26s}{'mean':>11s}{'std':>10s}"
                     f"{'cv%':>8s}{'min':>10s}{'max':>10s}\n")
        for key, label in summary_lib.METRICS:
            s = result["stats"][key]
            lines.append(
                f"  {label:26s}{s['mean']:11.3f}{s['std']:10.3f}"
                f"{s['cv_percent']:8.1f}{s['min']:10.3f}{s['max']:10.3f}\n")
        lines.append(f"  Saved to: {result['path']}\n")
        self._append_log("".join(lines))
        stroke = result["stats"]["stroke_mm"]
        self.status_var.set(
            f"Summary: {len(result['runs'])} runs, stroke "
            f"{stroke['mean']:.2f} +/- {stroke['std']:.2f} mm "
            f"(cv {stroke['cv_percent']:.1f}%).")
        self.last_output_dir = Path(result["path"]).parent

    def _on_summary_error(self, payload):
        self.summary_button.configure(state=tk.NORMAL)
        self.status_var.set(f"Summary: {payload}")
        self._append_log(f"[Summary Error] {payload}\n")
