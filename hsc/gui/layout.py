#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Widget construction and logging plumbing for the main window.

New feature buttons go into the ``actions`` row in :meth:`_build_layout`;
new settings fields use :meth:`_label_entry` / :meth:`_label_combo`.
"""

import tkinter as tk
from tkinter import filedialog, ttk

from hsc.gui.config import ASPECT_PRESETS, IMAGE_EXTENSIONS, ROOT, log_to_file


class LayoutMixin:
    """Builds the widget tree and owns the on-screen + on-disk log."""

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
        ttk.Checkbutton(checks, text="Smart save", variable=self.smart_save_var).pack(
            side=tk.LEFT, padx=(16, 0)
        )
        ttk.Checkbutton(checks, text="Timestamp folder", variable=self.timestamp_dir_var).pack(
            side=tk.LEFT, padx=(16, 0)
        )
        ttk.Checkbutton(checks, text="Test only, do not save", variable=self.no_save_var).pack(
            side=tk.LEFT, padx=(16, 0)
        )
        ttk.Checkbutton(checks, text="Edge detection V2", variable=self.edge_v2_var).pack(
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
        log_to_file(text)

    def _report_callback_exception(self, exc, val, tb):
        """Catch-all for uncaught Tk callback errors: log the traceback (which
        would otherwise be written to a missing stderr) and surface it briefly."""
        import traceback

        log_to_file("[Callback Error]\n" + "".join(traceback.format_exception(exc, val, tb)))
        try:
            self.status_var.set(f"Unexpected error: {val}")
        except Exception:
            pass
