#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Widget construction and logging plumbing for the main window.

New feature buttons go into one of the three button sections in
:meth:`_build_layout` (Operation / Workflow / Initial Setup); new settings
fields use :meth:`_label_entry` / :meth:`_label_combo`.
"""

import tkinter as tk
from tkinter import filedialog, ttk

from hsc.gui.config import CAPTURE_ROIS, ROI_FPS, ROOT, log_to_file


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

        # Left column: settings on top, then the three button sections. It is
        # SCROLLABLE, because the column keeps growing as settings are added
        # and on a laptop screen it eventually pushes the Operation buttons and
        # the Output log off the bottom with no way to reach them. Scrolling
        # the column (rather than the window) keeps the live preview and the
        # log where they are.
        left = self._scrollable_column(top)

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
        exposure_entry = self._label_entry(
            controls, "Exposure (us)", self.exposure_var, 1, 0)
        # An exposure longer than the frame period caps the rate AND washes the
        # piston out; keep the hint honest as it is typed.
        exposure_entry.bind("<KeyRelease>", lambda _e: self._update_roi_hint())
        # Capture ROI: a shorter frame reads out faster (see CAPTURE_ROIS).
        # Image type is fixed at .bmp (ext_var default).
        ttk.Label(controls, text="Capture ROI").grid(
            row=1, column=2, sticky="w", pady=(0, 8))
        roi_box = ttk.Frame(controls)
        roi_box.grid(row=1, column=3, sticky="ew", padx=(8, 16), pady=(0, 8))
        roi_box.columnconfigure(0, weight=1)
        self.roi_combo = ttk.Combobox(
            roi_box, textvariable=self.aspect_var, values=CAPTURE_ROIS,
            state="readonly", width=9)
        self.roi_combo.grid(row=0, column=0, sticky="ew")
        self.roi_fps_label = ttk.Label(roi_box, text="")
        self.roi_fps_label.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.roi_combo.bind("<<ComboboxSelected>>", self._on_roi_change)
        self._update_roi_hint()

        # Appended to every run folder and to the report/plot/video names.
        self._label_entry(controls, "Run label (optional)",
                          self.run_label_var, 2, 0)
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
            ("Find piston V2", self.piston_v2_var, None),
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
        # Piston fallback frame rate: only used for folders with no recorded
        # timing (Capture Piston writes per-frame timestamps).
        self._label_entry(workflow, "Piston FPS (if no meta)",
                          self.piston_fps_var, 2, 0)
        # Injector geometry -> jet speed / pressure (measure_piston).
        self._label_entry(workflow, "Barrel dia (mm)", self.barrel_mm_var, 2, 2)
        self._label_entry(workflow, "Orifice dia (mm)", self.orifice_mm_var, 3, 0)
        self.extract_button = ttk.Button(
            workflow, text="Find Injection", command=self._find_injection)
        self.measure_button = ttk.Button(
            workflow, text="Measure", command=self._measure_injection)
        self.video_button = ttk.Button(
            workflow, text="Make Video", command=self._make_video)
        self.piston_find_button = ttk.Button(
            workflow, text="Find Injection Piston",
            command=self._find_piston_injection)
        self.piston_measure_button = ttk.Button(
            workflow, text="Measure Piston", command=self._measure_piston)
        grid_buttons(workflow,
                     (self.extract_button, self.measure_button,
                      self.video_button, self.piston_find_button,
                      self.piston_measure_button), 3, first_row=4)

        # Operation: what the user touches every run.
        operation = section("Operation", 4)
        self.preview_button = ttk.Button(
            operation, text="Stop Preview", command=self._toggle_preview)
        # Capture toggles to "Stop Capture" while a burst runs (_run_capture).
        self.run_button = ttk.Button(
            operation, text="Capture", command=self._run_capture)
        self.monitor_button = ttk.Button(
            operation, text="Start Monitoring", command=self._toggle_monitor)
        # Toggles to "Stop Piston" while the burst runs (_capture_piston).
        self.piston_button = ttk.Button(
            operation, text="Capture Piston", command=self._capture_piston)
        self.open_button = ttk.Button(
            operation, text="Open Last Folder", command=self._open_last_folder)
        grid_buttons(operation,
                     (self.preview_button, self.run_button,
                      self.monitor_button, self.piston_button,
                      self.open_button), 4)

        log_frame = ttk.LabelFrame(root, text="Output", padding=8)
        log_frame.pack(fill=tk.X)
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=10)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _scrollable_column(self, parent):
        """A vertically scrollable frame in ``parent``'s grid cell (0, 0).

        Returns the inner frame to pack content into. The scrollbar appears
        only when the content is taller than the space available, so a roomy
        screen looks exactly as it did before.
        """
        holder = ttk.Frame(parent)
        holder.grid(row=0, column=0, sticky="nsew")
        canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def fit(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            needed = inner.winfo_reqheight() > canvas.winfo_height()
            if needed and not bar.winfo_ismapped():
                bar.pack(side=tk.RIGHT, fill=tk.Y)
            elif not needed and bar.winfo_ismapped():
                bar.pack_forget()
                canvas.yview_moveto(0.0)

        def stretch(event):
            canvas.itemconfigure(window, width=event.width)
            fit()

        inner.bind("<Configure>", fit)
        canvas.bind("<Configure>", stretch)

        def wheel(event):
            if bar.winfo_ismapped():
                canvas.yview_scroll(-int(event.delta / 120), "units")

        # Bound while the pointer is over the column, so the wheel still
        # belongs to whatever else it is over the rest of the time.
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        self.settings_canvas = canvas
        return inner

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
