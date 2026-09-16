#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Widget construction and logging plumbing for the main window.

New feature buttons go into one of the three button sections in
:meth:`_build_layout` (Operation / Workflow / Initial Setup); new settings
fields use :meth:`_label_entry` / :meth:`_label_combo`.
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

        # Left column: settings on top, then the three button sections.
        left = ttk.Frame(top)
        left.grid(row=0, column=0, sticky="nsew")

        controls = ttk.LabelFrame(left, text="Capture Settings", padding=12)
        controls.pack(fill=tk.X)
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

        def section(title, columns):
            frame = ttk.LabelFrame(left, text=title, padding=12)
            frame.pack(fill=tk.X, pady=(12, 0))
            for col in range(columns):
                frame.columnconfigure(col, weight=1, uniform=title)
            return frame

        def grid_buttons(frame, buttons, columns, first_row=0):
            for i, btn in enumerate(buttons):
                row, col = divmod(i, columns)
                btn.grid(row=first_row + row, column=col, sticky="ew",
                         padx=(0 if col == 0 else 8, 0),
                         pady=(0 if row == 0 and first_row == 0 else 8, 0))

        # Initial Setup: calibration / reference, done once per rig setup.
        setup = section("Initial Setup", 3)
        self._label_entry(setup, "Cal. distance (mm)", self.ref_mm_var, 0, 0)
        self.scale_button = ttk.Button(
            setup, text="Calibrate Scale", command=self._calibrate_scale)
        self.autoscale_button = ttk.Button(
            setup, text="Auto Calibrate",
            command=lambda: self._calibrate_scale(auto=True))
        self.measblock_button = ttk.Button(
            setup, text="Measure Block", command=self._measure_block_size)
        self.block_button = ttk.Button(
            setup, text="Measure Angle Block", command=self._measure_block)
        self.reference_button = ttk.Button(
            setup, text="Set Reference", command=self._set_reference)
        grid_buttons(setup,
                     (self.scale_button, self.autoscale_button,
                      self.measblock_button, self.block_button,
                      self.reference_button), 3, first_row=1)

        # Workflow: the find -> measure -> video chain and its options.
        workflow = section("Workflow", 4)
        checks = ttk.Frame(workflow)
        checks.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        # Checkboxes wrap to a second row (5 don't fit in one at the
        # default window width).
        checkboxes = (
            ("Smart save", self.smart_save_var, None),
            ("Edge detection V2", self.edge_v2_var, None),
            ("Reference on preview", self.show_ref_var,
             self._refresh_preview_reference),
            ("Auto pick frames", self.auto_pick_var, self._toggle_auto_pick),
            ("Ref. lines on output", self.ref_lines_var, None),
        )
        for i, (text, var, command) in enumerate(checkboxes):
            row, col = divmod(i, 3)
            kwargs = {"command": command} if command else {}
            ttk.Checkbutton(checks, text=text, variable=var, **kwargs).grid(
                row=row, column=col, sticky="w",
                padx=(0 if col == 0 else 16, 0), pady=(0 if row == 0 else 4, 0),
            )
        self.measure_start_entry = self._label_entry(
            workflow, "Measure from (Nth)", self.measure_start_var, 1, 0)
        self.measure_end_entry = self._label_entry(
            workflow, "Measure to (Nth)", self.measure_end_var, 1, 2)
        self.extract_button = ttk.Button(
            workflow, text="Find Injection", command=self._find_injection)
        self.measure_button = ttk.Button(
            workflow, text="Measure", command=self._measure_injection)
        self.video_button = ttk.Button(
            workflow, text="Make Video", command=self._make_video)
        grid_buttons(workflow,
                     (self.extract_button, self.measure_button,
                      self.video_button), 3, first_row=2)

        # Operation: what the user touches every run.
        operation = section("Operation", 4)
        self.preview_button = ttk.Button(
            operation, text="Stop Preview", command=self._toggle_preview)
        # Capture toggles to "Stop Capture" while a burst runs (_run_capture).
        self.run_button = ttk.Button(
            operation, text="Capture", command=self._run_capture)
        self.monitor_button = ttk.Button(
            operation, text="Start Monitoring", command=self._toggle_monitor)
        self.open_button = ttk.Button(
            operation, text="Open Last Folder", command=self._open_last_folder)
        grid_buttons(operation,
                     (self.preview_button, self.run_button,
                      self.monitor_button, self.open_button), 4)

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
