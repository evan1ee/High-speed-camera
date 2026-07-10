#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Widget construction and logging plumbing for the main window.

New feature buttons go into the ``actions`` row in :meth:`_build_layout`;
new settings fields use :meth:`_label_entry` / :meth:`_label_combo`.
"""

import tkinter as tk
from tkinter import filedialog, ttk

from hsc.gui.config import ROOT, log_to_file


class LayoutMixin:
    """Builds the widget tree and owns the on-screen + on-disk log."""

    def _build_layout(self):
        # Status bar first (packed at the window bottom so the main area
        # keeps the remaining space), like a standard desktop app.
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Frame(self)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Separator(status_bar, orient=tk.HORIZONTAL).pack(fill=tk.X)
        ttk.Label(status_bar, textvariable=self.status_var,
                  padding=(12, 4)).pack(side=tk.LEFT)

        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.BOTH, expand=True)
        # Two uniform columns: settings left, live preview right -- the
        # preview always gets exactly half the window width.
        top.columnconfigure(0, weight=1, uniform="half")
        top.columnconfigure(1, weight=1, uniform="half")
        top.rowconfigure(0, weight=1)

        controls = ttk.LabelFrame(top, text="Capture Settings", padding=12)
        controls.grid(row=0, column=0, sticky="nsew")
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        self.preview_frame = ttk.LabelFrame(top, text="Live Preview", padding=8)
        self.preview_frame.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.preview_label = ttk.Label(self.preview_frame, text="Starting preview...", anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        # Re-fit the live image whenever the pane changes size.
        self.preview_frame.bind("<Configure>", self._on_preview_resize)

        self._label_entry(controls, "Capture time (s)", self.duration_var, 0, 0)
        self._label_entry(controls, "Camera index", self.camera_index_var, 0, 2)
        self._label_entry(controls, "Exposure (us)", self.exposure_var, 1, 0)
        # Fixed, no selector shown: aspect preset = 320x240 (aspect_var
        # default), image type = .bmp (ext_var default).

        ttk.Label(controls, text="Output base folder").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(controls, textvariable=self.output_dir_var).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=(8, 0)
        )
        ttk.Button(controls, text="Browse", command=self._browse_output_dir).grid(
            row=3, column=3, sticky="ew", pady=(8, 0)
        )

        checks = ttk.Frame(controls)
        checks.grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))
        # Two rows of checkboxes (row, column in the checks grid).
        checkboxes = (
            ("Defer save", self.defer_save_var, None),
            ("Smart save", self.smart_save_var, None),
            ("Timestamp folder", self.timestamp_dir_var, None),
            ("Test only, do not save", self.no_save_var, None),
            ("Edge detection V2", self.edge_v2_var, None),
            ("Reference on preview", self.show_ref_var,
             self._refresh_preview_reference),
            ("Auto pick frames", self.auto_pick_var, self._toggle_auto_pick),
        )
        per_row = (len(checkboxes) + 1) // 2
        for i, (text, var, command) in enumerate(checkboxes):
            row, col = divmod(i, per_row)
            kwargs = {"command": command} if command else {}
            ttk.Checkbutton(checks, text=text, variable=var, **kwargs).grid(
                row=row, column=col, sticky="w",
                padx=(0 if col == 0 else 16, 0), pady=(0 if row == 0 else 6, 0),
            )

        self._label_entry(controls, "Frames before injection", self.before_var, 5, 0)
        self._label_entry(controls, "Frames after injection", self.after_var, 5, 2)
        self.measure_start_entry = self._label_entry(
            controls, "Measure from (Nth)", self.measure_start_var, 6, 0)
        self.measure_end_entry = self._label_entry(
            controls, "Measure to (Nth)", self.measure_end_var, 6, 2)
        self._label_entry(controls, "Cal. distance (mm)", self.ref_mm_var, 7, 0)

        # Action buttons: a uniform grid filling the empty space at the
        # bottom of the settings panel (left column, under the fields).
        controls.rowconfigure(8, weight=1)
        actions = ttk.Frame(controls)
        actions.grid(row=8, column=0, columnspan=4, sticky="new", pady=(12, 0))
        for col in range(4):
            actions.columnconfigure(col, weight=1, uniform="btn")

        self.preview_button = ttk.Button(actions, text="Stop Preview", command=self._toggle_preview)
        self.run_button = ttk.Button(actions, text="Capture", command=self._run_capture)
        self.stop_button = ttk.Button(actions, text="Stop", command=self._stop_capture, state=tk.DISABLED)
        self.monitor_button = ttk.Button(
            actions, text="Start Monitoring", command=self._toggle_monitor
        )
        self.extract_button = ttk.Button(
            actions, text="Find Injection", command=self._find_injection
        )
        self.measure_button = ttk.Button(
            actions, text="Measure", command=self._measure_injection
        )
        self.video_button = ttk.Button(
            actions, text="Make Video", command=self._make_video
        )
        self.scale_button = ttk.Button(
            actions, text="Calibrate Scale", command=self._calibrate_scale
        )
        self.autoscale_button = ttk.Button(
            actions, text="Auto Calibrate",
            command=lambda: self._calibrate_scale(auto=True),
        )
        self.measblock_button = ttk.Button(
            actions, text="Measure Block", command=self._measure_block_size
        )
        self.block_button = ttk.Button(
            actions, text="Measure Angle Block", command=self._measure_block
        )
        self.reference_button = ttk.Button(
            actions, text="Set Reference", command=self._set_reference
        )
        self.open_button = ttk.Button(actions, text="Open Last Folder", command=self._open_last_folder)

        buttons = (
            self.preview_button, self.run_button, self.stop_button,
            self.monitor_button,
            self.extract_button, self.measure_button, self.video_button,
            self.scale_button, self.autoscale_button, self.measblock_button,
            self.block_button, self.reference_button, self.open_button,
        )
        for i, btn in enumerate(buttons):
            row, col = divmod(i, 4)
            btn.grid(row=row, column=col, sticky="ew",
                     padx=(0 if col == 0 else 8, 0), pady=(0 if row == 0 else 8, 0))

        log_frame = ttk.LabelFrame(root, text="Output", padding=8)
        log_frame.pack(fill=tk.X)
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=10)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _label_entry(self, parent, label, variable, row, column):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", pady=(0, 8))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=column + 1, sticky="ew", padx=(8, 16), pady=(0, 8))
        return entry

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
