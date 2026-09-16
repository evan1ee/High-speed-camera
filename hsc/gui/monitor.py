#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Monitor mode: continuous multi-injection capture.

UI side of the Start/Stop Monitoring toggle. The camera side
(:meth:`hsc.gui.camera_worker.CameraWorkerMixin._do_monitor`) streams frames
through :class:`hsc.monitor.MonitorEngine` and hands each closed event to a
background :class:`hsc.frame_writer.EventWriter`; this mixin holds each
event's result until MONITOR_SAVED confirms the frames are ON DISK, then
feeds them one at a time through the existing measure -> video chain.
"""

import threading
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

from hsc.gui.config import PAD_AFTER, PAD_BEFORE


class MonitorMixin:
    """Start/Stop Monitoring button, queue handlers, and the chain pump."""

    QUEUE_HANDLERS = {
        "MONITOR_EVENT": "_on_monitor_event",
        "MONITOR_SAVED": "_on_monitor_saved",
        "MONITOR_STOPPED": "_on_monitor_stopped",
    }

    #: Camera-owning buttons greyed out while monitoring (the camera thread
    #: is busy in _do_monitor, so capture/still requests would stall).
    MONITOR_DISABLED_BUTTONS = (
        "run_button", "scale_button", "autoscale_button",
        "measblock_button", "block_button", "reference_button",
        "piston_button", "gel_button",
    )

    def _init_monitor_state(self):
        self.monitor_requested = threading.Event()
        self.monitor_stop = threading.Event()
        self.monitor_active = False
        self.monitor_params = None
        # Snapshot of the run label, set by the camera thread at _do_monitor.
        self.monitor_label = ""
        # Events detected but not yet confirmed written (keyed by dest_dir).
        self._monitor_results = {}
        # Events safely on disk, awaiting their measure run (FIFO).
        self._monitor_chain = []
        # True while a monitor event is inside the measure chain; tells
        # _maybe_auto_video_after_measure to skip the slow-motion video
        # (not wanted in monitor mode) and pump the next event instead.
        self._monitor_chain_active = False

    # ------------------------------------------------------------------
    # Button
    # ------------------------------------------------------------------
    def _toggle_monitor(self):
        if self.monitor_active:
            self.monitor_stop.set()
            # Re-enabled by MONITOR_STOPPED once the worker confirms.
            self.monitor_button.configure(state=tk.DISABLED)
            return
        if self.capture_requested.is_set() or self.piston_requested.is_set():
            self.status_var.set("Finish the capture first.")
            return
        # Fixed padding (former entry fields); snapshotted here because the
        # camera thread must not touch the UI.
        self.monitor_params = SimpleNamespace(
            before=PAD_BEFORE, after=PAD_AFTER,
            label=self.run_label_var.get())
        # Camera must be open and grabbing; the worker picks the request up
        # on its next loop iteration (same pattern as Capture).
        if not (self.camera_thread and self.camera_thread.is_alive()):
            self._start_preview()
        self.monitor_stop.clear()
        self.monitor_active = True
        self.monitor_button.configure(text="Stop Monitoring")
        for name in self.MONITOR_DISABLED_BUTTONS:
            getattr(self, name).configure(state=tk.DISABLED)
        self.monitor_requested.set()
        self.status_var.set("Monitoring...")

    # ------------------------------------------------------------------
    # Queue handlers
    # ------------------------------------------------------------------
    def _on_monitor_event(self, result):
        # Hold the result until MONITOR_SAVED confirms the frames are ON
        # DISK -- the writer is asynchronous, and measure/video must never
        # start on a half-written folder.
        self._monitor_results[result["dest_dir"]] = result

    def _on_monitor_saved(self, payload):
        dest_dir, ok, msg = payload
        self._append_log(
            f"[Monitor save] {Path(dest_dir).name}: "
            f"{msg if ok else 'ERROR ' + msg}\n")
        result = self._monitor_results.pop(dest_dir, None)
        if ok and result is not None:
            self._monitor_chain.append(result)
            self._pump_monitor_chain()

    def _on_monitor_stopped(self, payload):
        self._reset_monitor_ui()
        self._append_log(str(payload) + "\n")
        self.status_var.set("Monitoring stopped")
        # Any events still queued (e.g. the flushed partial one) keep flowing.
        self._pump_monitor_chain()

    # ------------------------------------------------------------------
    # Chain pump: one event at a time through measure (no video)
    # ------------------------------------------------------------------
    def _pump_monitor_chain(self):
        """Start the measure run for the next saved event, if the chain is idle.

        Re-invoked when the previous event's measurement finishes (via
        _maybe_auto_video_after_measure, which skips the video for monitor
        events) so queued events are processed strictly one at a time.
        """
        busy = (
            (self.extract_thread and self.extract_thread.is_alive())
            or (self.measure_thread and self.measure_thread.is_alive())
            or (self.video_thread and self.video_thread.is_alive())
        )
        if busy or not self._monitor_chain:
            return
        result = self._monitor_chain.pop(0)
        self.auto_measure_pending = True
        self._monitor_chain_active = True
        # Per-event wall time: logged by _on_measure_done as the usual
        # "Total time (find injection -> measurement finished)" line.
        self._pipeline_t0 = time.perf_counter()
        self._on_extract_done(result)

    def _reset_monitor_ui(self):
        """Return the monitor toggle + camera buttons to idle. Idempotent;
        also called when the camera thread stops for any reason."""
        self.monitor_active = False
        self.monitor_stop.clear()
        self.monitor_requested.clear()
        self.monitor_button.configure(text="Start Monitoring", state=tk.NORMAL)
        for name in self.MONITOR_DISABLED_BUTTONS:
            getattr(self, name).configure(state=tk.NORMAL)
