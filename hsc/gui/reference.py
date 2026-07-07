#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Set Reference: capture a nozzle still (no jet) and open the dialog where
the user draws the tip edge; the centerline + rectangle are built from it."""

import threading
import tkinter as tk
from pathlib import Path

from hsc import reference_ui
from hsc.gui.config import REFERENCE_DIR


class ReferenceMixin:
    """Nozzle reference-line actions + queue handlers."""

    QUEUE_HANDLERS = {
        "REFERENCE_CAPTURED": "_open_reference_dialog",
        "REFERENCE_ERROR": "_on_reference_error",
    }

    def _init_reference_state(self):
        self.reference_requested = threading.Event()

        self.register_still_request(
            self.reference_requested, "nozzle", "REFERENCE_CAPTURED",
            "REFERENCE_ERROR", REFERENCE_DIR, buttons=("reference_button",),
        )

    def _set_reference(self):
        if self.reference_requested.is_set():
            return
        # Capture a still of the nozzle (no jet), then detect the tip on it.
        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()
        self._append_log("Capturing nozzle still for reference lines...\n")
        self.status_var.set("Capturing nozzle...")
        self.reference_button.configure(state=tk.DISABLED)
        self.reference_requested.set()

    def _open_reference_dialog(self, path):
        """Open the mark-and-detect reference dialog on the captured nozzle still."""
        self.reference_button.configure(state=tk.NORMAL)
        self._append_log(
            f"Captured {path}\n"
            "Draw a box on the nozzle tip, then click 'Detect Edge'.\n"
        )
        try:
            reference_ui.ReferenceDialog(
                self, path, nozzle_side=1, on_saved=self._on_reference_done
            )
        except Exception as exc:
            self.status_var.set(f"Reference: {exc}")
            self._append_log(f"[Reference Error] {exc}\n")

    def _on_reference_done(self, ref):
        self.reference_button.configure(state=tk.NORMAL)
        self._append_log(
            "Nozzle reference set.\n"
            f"  Tip edge (red):    x={ref['nozzle_p0'][0]:.0f}, "
            f"y={ref['nozzle_p0'][1]:.0f}..{ref['nozzle_p1'][1]:.0f}\n"
            f"  Centerline (blue): y={ref['mid'][1]:.0f}\n"
            f"  Saved to:  {ref.get('reference_file', '?')}\n"
            f"  Check img: {ref['annotated']}\n"
            "  Now overlaid on measured frames. Re-set it if the nozzle/camera moves.\n"
        )
        self.status_var.set(f"Nozzle reference set (centerline y={ref['mid'][1]:.0f}).")
        self.last_output_dir = Path(ref["annotated"]).parent

    def _on_reference_error(self, payload):
        self.status_var.set(f"Reference: {payload}")
        self._append_log(f"[Reference Error] {payload}\n")
        self.reference_button.configure(state=tk.NORMAL)
