#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Interactive ROI calibration dialog (Tkinter).

Shows a captured still; the user drags a box around each of the two reference
edges, clicks *Detect Edge*, and the software fits a sub-pixel green line inside
each ROI (see ``calibrate_scale``), measures the pixel gap and reports mm/px.
*Save Calibration* writes ``calibration.json`` and an annotated image. The user
can redraw either ROI and re-detect for immediate visual feedback.
"""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from hsc import calibrate_scale
from hsc import measure_angle as ma


ROI_COLORS = ("#00e0ff", "#ff9000")   # upper, lower
LINE_COLOR = "#00ff00"
MAX_DISPLAY_W = 960
MAX_DISPLAY_H = 680


class CalibrationDialog(tk.Toplevel):
    def __init__(self, parent, image_path, ref_mm=10.0, on_saved=None):
        super().__init__(parent)
        self.title("Calibrate Scale - draw an ROI around each reference edge")
        self.image_path = image_path
        self.on_saved = on_saved
        self.gray = ma.load_gray(image_path)
        h, w = self.gray.shape
        self.scale = min(MAX_DISPLAY_W / w, MAX_DISPLAY_H / h)
        self.scale = max(1.0, min(self.scale, 5.0))
        self.disp_w, self.disp_h = int(w * self.scale), int(h * self.scale)

        self.rois = [None, None]          # image-coord (x0,y0,x1,y1)
        self.active = 0                   # 0 = upper, 1 = lower
        self._drag_start = None
        self._rubber = None
        self._line_ids = []
        self.result = None

        self.ref_mm_var = tk.StringVar(value=f"{float(ref_mm):g}")
        self.status_var = tk.StringVar(value="Step 1: drag a box around the UPPER edge.")
        self._build()
        self._redraw_rois()
        self.transient(parent)
        self.grab_set()

    # ---- layout ----------------------------------------------------------
    def _build(self):
        bar = ttk.Frame(self, padding=8)
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(bar, text="Known distance (mm):").pack(side=tk.LEFT)
        ttk.Entry(bar, textvariable=self.ref_mm_var, width=8).pack(side=tk.LEFT, padx=(4, 12))
        self.upper_btn = ttk.Button(bar, text="Draw Upper ROI",
                                    command=lambda: self._set_active(0))
        self.upper_btn.pack(side=tk.LEFT)
        self.lower_btn = ttk.Button(bar, text="Draw Lower ROI",
                                    command=lambda: self._set_active(1))
        self.lower_btn.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Button(bar, text="Detect Edge", command=self._detect).pack(side=tk.LEFT)
        self.save_btn = ttk.Button(bar, text="Save Calibration",
                                   command=self._save, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=(4, 0))

        self.canvas = tk.Canvas(self, width=self.disp_w, height=self.disp_h,
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack(padx=8)
        disp = Image.fromarray(self.gray).convert("RGB").resize(
            (self.disp_w, self.disp_h), Image.NEAREST)
        self._photo = ImageTk.PhotoImage(disp)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        ttk.Label(self, textvariable=self.status_var, padding=(8, 4)).pack(
            side=tk.TOP, anchor=tk.W)

    def _set_active(self, idx):
        self.active = idx
        which = "UPPER" if idx == 0 else "LOWER"
        self.status_var.set(f"Drag a box around the {which} edge.")

    # ---- ROI drawing -----------------------------------------------------
    def _on_press(self, ev):
        self._drag_start = (ev.x, ev.y)
        if self._rubber:
            self.canvas.delete(self._rubber)
        self._rubber = self.canvas.create_rectangle(
            ev.x, ev.y, ev.x, ev.y, outline=ROI_COLORS[self.active], width=2)

    def _on_drag(self, ev):
        if self._drag_start and self._rubber:
            self.canvas.coords(self._rubber, self._drag_start[0],
                               self._drag_start[1], ev.x, ev.y)

    def _on_release(self, ev):
        if not self._drag_start:
            return
        x0, y0 = self._drag_start
        x1, y1 = ev.x, ev.y
        self._drag_start = None
        if abs(x1 - x0) < 4 or abs(y1 - y0) < 4:
            return
        self.rois[self.active] = (min(x0, x1) / self.scale, min(y0, y1) / self.scale,
                                  max(x0, x1) / self.scale, max(y0, y1) / self.scale)
        if self.active == 0 and self.rois[1] is None:
            self._set_active(1)
        else:
            self.status_var.set("Both ROIs set. Click 'Detect Edge'.")
        self._redraw_rois()

    def _redraw_rois(self):
        self.canvas.delete("roi")
        for i, roi in enumerate(self.rois):
            if roi is None:
                continue
            x0, y0, x1, y1 = [v * self.scale for v in roi]
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=ROI_COLORS[i],
                                         width=2, tags="roi")
        if self._rubber:
            self.canvas.delete(self._rubber)
            self._rubber = None

    # ---- detect / save ---------------------------------------------------
    def _clear_lines(self):
        for lid in self._line_ids:
            self.canvas.delete(lid)
        self._line_ids = []

    def _draw_line(self, edge):
        w = self.gray.shape[1]
        h = self.gray.shape[0]
        if edge["horizontal"]:
            a = (0, edge["b"]); c = (w - 1, edge["k"] * (w - 1) + edge["b"])
        else:
            a = (edge["b"], 0); c = (edge["k"] * (h - 1) + edge["b"], h - 1)
        lid = self.canvas.create_line(a[0] * self.scale, a[1] * self.scale,
                                      c[0] * self.scale, c[1] * self.scale,
                                      fill=LINE_COLOR, width=2)
        self._line_ids.append(lid)

    def _detect(self):
        if self.rois[0] is None or self.rois[1] is None:
            self.status_var.set("Draw both ROIs first (upper and lower edge).")
            return
        try:
            ref_mm = float(self.ref_mm_var.get())
            if ref_mm <= 0:
                raise ValueError
        except ValueError:
            self.status_var.set("Known distance must be a positive number (mm).")
            return
        try:
            self.result = calibrate_scale.calibrate_from_rois(
                self.gray, self.rois[0], self.rois[1], ref_mm)
        except Exception as exc:
            self.status_var.set(f"Detect failed: {exc}")
            return
        self._clear_lines()
        self._draw_line(self.result["edge1"])
        self._draw_line(self.result["edge2"])
        self.status_var.set(
            f"Pixel distance: {self.result['gap_px']:.2f} px    "
            f"Scale: {self.result['mm_per_px']:.5f} mm/pixel "
            f"({self.result['px_per_mm']:.2f} px/mm)  -  adjust an ROI and "
            "re-detect, or Save."
        )
        self.save_btn.configure(state=tk.NORMAL)

    def _save(self):
        if not self.result:
            return
        record = calibrate_scale.save_calibration(self.result, self.image_path)
        self.status_var.set(
            f"Saved: {record['mm_per_px']:.5f} mm/px -> {record.get('calibration_file', '?')}"
        )
        if self.on_saved:
            self.on_saved(record)
        self.after(600, self.destroy)
