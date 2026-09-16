#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Gel injection: capture, find the injection images, make a slow-motion video.

The jet is fired **into a gel block** rather than into open air, so this is the
spray capture path with two differences and no measurement:

* **The scene never clears.** The gel stays deformed and dyed, so the default
  end rule -- presence inside the jet mask settling back toward the pre-onset
  background -- has no trough that means "jet gone" and runs far past the
  event. The gel path therefore asks for ``end_rule="temporal"``: frame-to-frame
  motion DOES stop once the gel stops moving. On a synthetic permanently-changed
  scene the temporal rule lands on the last moving frame where the presence rule
  overshoots it by 187 frames (``tests/test_gel_end_rule.py``).
* **No spray angle.** There is no free jet to fit edge lines to inside a gel
  block, so the chain ends at the video: capture -> find injection -> slow-mo.

Smart save is forced off. Its detect-before-write branch plans the copy window
from the jet's motion signal using the *presence* rule, which is the rule this
path exists to avoid -- so the burst is written in full and the injection is
found from disk, where ``end_rule`` can be chosen.
"""

import tkinter as tk


class GelMixin:
    """Capture Gel Injection (Operation) and its capture -> find -> video chain."""

    def _init_gel_state(self):
        # Set while a gel capture's chain is running, so _on_capture_done skips
        # the measure step and _on_extract_done goes straight to the video.
        self.gel_chain = False

    def _capture_gel(self):
        if self.capture_requested.is_set():
            # Second click = abort, same contract as Capture.
            self.capture_abort.set()
            self.status_var.set("Aborting gel capture...")
            return
        if self.piston_requested.is_set() or self.monitor_active:
            self.status_var.set("Finish the running capture first.")
            return

        try:
            params = self._build_capture_params()
        except ValueError as exc:
            self.status_var.set(str(exc))
            return

        # A gel run is written whole and named so it is identifiable on disk;
        # the injection-images and measure folders inherit the name for free,
        # because make_dest_dir names them after the source.
        params.smart_save = False
        params.run_prefix = "gel"

        self.capture_params = params
        self.last_output_dir = None
        self.log_text.delete("1.0", tk.END)
        self.gel_chain = True
        self.gel_button.configure(text="Stop Gel")
        self.run_button.configure(state=tk.DISABLED)

        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()

        self.capture_abort.clear()
        self.capture_requested.set()
        self.status_var.set("Capturing gel injection...")

    def _reset_gel_ui(self):
        """Return the Capture Gel Injection toggle to idle. Idempotent; also
        called when the camera thread stops for any reason."""
        self.gel_button.configure(text="Capture Gel Injection", state=tk.NORMAL)
