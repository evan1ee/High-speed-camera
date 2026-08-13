#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The main window: assembles the feature mixins and dispatches queue messages.

Adding a new feature module:

1. Write a mixin in a new ``hsc/gui/<feature>.py``: action methods, worker
   methods that post ``(KIND, payload)`` tuples to ``self.output_queue``, an
   ``_init_<feature>_state`` method for its attributes/Tk variables, and a
   ``QUEUE_HANDLERS`` dict mapping each message kind to its handler method.
   If it needs a single still from the camera, call
   ``self.register_still_request(...)`` in its state init.
2. Add the mixin to :class:`CaptureGui`'s bases and call its state init in
   ``__init__`` below.
3. Add its button/fields in :mod:`hsc.gui.layout`.
"""

import queue
import tkinter as tk

from hsc.gui.calibration import CalibrationMixin
from hsc.gui.camera_worker import CameraWorkerMixin
from hsc.gui.capture import CaptureMixin
from hsc.gui.config import log_to_file
from hsc.gui.extraction import ExtractionMixin
from hsc.gui.layout import LayoutMixin
from hsc.gui.measurement import MeasurementMixin
from hsc.gui.monitor import MonitorMixin
from hsc.gui.piston import PistonMixin
from hsc.gui.reference import ReferenceMixin
from hsc.gui.summary import SummaryMixin
from hsc.gui.video import VideoMixin


class CaptureGui(
    LayoutMixin,
    CaptureMixin,
    CameraWorkerMixin,
    ExtractionMixin,
    MeasurementMixin,
    MonitorMixin,
    PistonMixin,
    SummaryMixin,
    VideoMixin,
    CalibrationMixin,
    ReferenceMixin,
    tk.Tk,
):
    QUEUE_HANDLERS = {
        "STATUS": "_on_status",
    }

    def __init__(self):
        super().__init__()
        self.title("High Speed Camera Capture")
        self.geometry("980x680")
        self.minsize(860, 600)
        # Launch maximized.
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-zoomed", True)

        self.output_queue = queue.Queue()
        self.preview_queue = queue.Queue()
        self.last_output_dir = None
        self.last_injection_dir = None

        # Per-feature state (attributes + Tk variables). Capture goes first:
        # it owns the still-request registry the other features register with.
        self._init_capture_state()
        self._init_monitor_state()
        self._init_piston_state()
        self._init_extraction_state()
        self._init_measurement_state()
        self._init_video_state()
        self._init_calibration_state()
        self._init_reference_state()
        self._init_summary_state()

        # Uncaught Tk callback errors must not vanish (stderr is None when the
        # build is frozen/windowed) -- send the traceback to app.log.
        self.report_callback_exception = self._report_callback_exception

        self._queue_handlers = self._collect_queue_handlers()
        self._build_layout()
        self.after(100, self._drain_output_queue)
        self.after(50, self._drain_preview_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Automatically start the live preview as soon as the GUI launches.
        self.after(200, self._start_preview)

    def _collect_queue_handlers(self):
        """Merge every mixin's ``QUEUE_HANDLERS`` into one kind -> bound-method
        map. Later classes in the MRO must not silently override earlier ones."""
        mapping = {}
        for klass in reversed(type(self).__mro__):
            for kind, name in vars(klass).get("QUEUE_HANDLERS", {}).items():
                if kind in mapping and mapping[kind] != name:
                    raise RuntimeError(
                        f"Queue message kind {kind!r} is handled by both "
                        f"{mapping[kind]!r} and {name!r}."
                    )
                mapping[kind] = name
        return {kind: getattr(self, name) for kind, name in mapping.items()}

    def _on_status(self, payload):
        self.status_var.set(payload)

    def _drain_output_queue(self):
        while True:
            try:
                item = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if isinstance(item, tuple):
                kind, payload = item
                handler = self._queue_handlers.get(kind)
                if handler is not None:
                    handler(payload)
                continue

            self._append_log(item)

        self.after(100, self._drain_output_queue)

    def _open_last_folder(self):
        import os
        from pathlib import Path

        folder = self.last_output_dir or Path(self.output_dir_var.get())
        if folder.exists():
            os.startfile(folder)
        else:
            self.status_var.set("No output folder found yet.")

    def _on_close(self):
        """Clean up resources when the window is closed."""
        try:
            self.preview_stop.set()
            self.capture_abort.set()
            if self.camera_thread and self.camera_thread.is_alive():
                self.camera_thread.join(timeout=2)
        except Exception as exc:
            log_to_file(f"[Close Error] {exc}")

        self.destroy()


def main(argv=None):
    """GUI entry point; ``--selftest <injection folder>`` runs headless."""
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 2 and argv[0] == "--selftest":
        from hsc.gui.selftest import run_selftest

        return run_selftest(argv[1])

    app = CaptureGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
