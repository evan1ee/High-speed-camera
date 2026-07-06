#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Interactive nozzle-reference dialog (Tkinter).

Auto-detecting the tip on the reflective nozzle is unreliable, so the user draws
the tip edge directly: **drag along the nozzle tip edge** (e.g. top to bottom)
to place the thin red line; the blue **centerline** (perpendicular, through the
edge midpoint, across the frame = spray axis) is built live. *Save* stores
``reference_lines.json`` and a native-resolution check image.
"""

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

import calibrate_scale
import reference_lines as rl


RED = "#ff0000"            # tip edge
BLUE = "#0080ff"           # centerline
MAX_DISPLAY_W = 960
MAX_DISPLAY_H = 680


class ReferenceDialog(tk.Toplevel):
    def __init__(self, parent, image_path, nozzle_side=1, on_saved=None):
        super().__init__(parent)
        self.title("Set Reference - drag along the nozzle tip edge to draw the red line")
        self.image_path = image_path
        self.nozzle_side = nozzle_side
        self.on_saved = on_saved
        self.gray = rl._load_gray(image_path)
        h, w = self.gray.shape
        self.scale = max(1.0, min(min(MAX_DISPLAY_W / w, MAX_DISPLAY_H / h), 5.0))
        self.disp_w, self.disp_h = int(w * self.scale), int(h * self.scale)

        self._drag_start = None
        self._ids = []
        self.ref = None

        self.status_var = tk.StringVar(
            value="Drag along the nozzle tip edge (top to bottom) to draw the red line.")
        self._build()
        self.transient(parent)
        self.grab_set()

    def _build(self):
        bar = ttk.Frame(self, padding=8)
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(bar, text="Drag = red tip edge; blue centerline is built automatically.").pack(
            side=tk.LEFT)
        self.redraw_btn = ttk.Button(bar, text="Redraw", command=self._redraw,
                                     state=tk.DISABLED)
        self.redraw_btn.pack(side=tk.LEFT, padx=(12, 0))
        self.save_btn = ttk.Button(bar, text="Save Reference",
                                   command=self._save, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=(6, 0))

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

    def _clear(self):
        for i in self._ids:
            self.canvas.delete(i)
        self._ids = []

    def _redraw(self):
        """Discard the current line so the user can draw a fresh one."""
        self._clear()
        self.ref = None
        self._drag_start = None
        self.save_btn.configure(state=tk.DISABLED)
        self.redraw_btn.configure(state=tk.DISABLED)
        self.status_var.set(
            "Drag along the nozzle tip edge (top to bottom) to draw the red line.")

    def _cline(self, a, b, color, width, dash=None):
        i = self.canvas.create_line(a[0] * self.scale, a[1] * self.scale,
                                    b[0] * self.scale, b[1] * self.scale,
                                    fill=color, width=width, dash=dash)
        self._ids.append(i)

    def _on_press(self, ev):
        self._drag_start = (ev.x / self.scale, ev.y / self.scale)
        self._clear()

    def _on_drag(self, ev):
        if not self._drag_start:
            return
        self._clear()
        p1 = (ev.x / self.scale, ev.y / self.scale)
        self._cline(self._drag_start, p1, RED, 2)

    def _on_release(self, ev):
        if not self._drag_start:
            return
        p0 = self._drag_start
        p1 = (ev.x / self.scale, ev.y / self.scale)
        self._drag_start = None
        h, w = self.gray.shape
        try:
            self.ref = rl.build_reference(p0, p1, (w, h))
        except Exception as exc:
            self.status_var.set(f"{exc}")
            return
        # Add the mm-sized rectangle if the scale is calibrated.
        cal = calibrate_scale.load_calibration()
        rect_note = ""
        if cal:
            rl.attach_rectangle(self.ref, cal["mm_per_px"], self.nozzle_side)
        else:
            rect_note = "  (no scale calibration -> rectangle skipped; run Calibrate Scale)"
        self._draw_all()
        self.status_var.set(
            f"Tip edge set (centerline y={self.ref['mid'][1]:.0f}). "
            f"Redraw if not good enough, or Save.{rect_note}")
        self.save_btn.configure(state=tk.NORMAL)
        self.redraw_btn.configure(state=tk.NORMAL)

    def _draw_all(self):
        self._clear()
        self._cline(self.ref["blue_a"], self.ref["blue_b"], BLUE, 1)
        self._cline(self.ref["nozzle_p0"], self.ref["nozzle_p1"], RED, 1)
        rect = self.ref.get("rect")
        if rect:
            x0, y0, x1, y1 = (v * self.scale for v in rect)
            i = self.canvas.create_rectangle(x0, y0, x1, y1, outline=RED, width=1)
            self._ids.append(i)

    def _save(self):
        if not self.ref:
            return
        out = Path(self.image_path).with_name(Path(self.image_path).stem + "_ref.bmp")
        self.ref["source"] = str(self.image_path)
        self.ref["annotated"] = rl.save_check_image(self.gray, self.ref, out)
        self.ref["reference_file"] = rl.save_reference(self.ref)
        self.status_var.set(f"Saved -> {self.ref['reference_file']}")
        if self.on_saved:
            self.on_saved(self.ref)
        self.after(500, self.destroy)
