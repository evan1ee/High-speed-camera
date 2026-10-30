#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Make Video: build the slow-motion playback video from an injection folder,
and chain the auto-measure step of the capture pipeline once it finishes."""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from hsc import make_video
from hsc.gui.config import INJECTION_DIR, ROOT


class VideoMixin:
    """Slow-motion video action + queue handlers."""

    QUEUE_HANDLERS = {
        "VIDEO_DONE": "_on_video_done",
        "VIDEO_ERROR": "_on_video_error",
    }

    def _init_video_state(self):
        self.video_thread = None

    def _make_video(self, source=None):
        if self.video_thread and self.video_thread.is_alive():
            return

        # Default to the last extracted injection folder; otherwise let the user
        # pick one from the "injection images" directory.
        if source is None:
            initial = self.last_injection_dir or (
                INJECTION_DIR if INJECTION_DIR.exists() else ROOT
            )
            picked = filedialog.askdirectory(
                title="Select an injection-images folder to build a slow-motion video",
                initialdir=str(initial),
            )
            if not picked:
                return
            source = Path(picked)
        else:
            source = Path(source)

        self._append_log(f"Building slow-motion video from {source} ...\n")
        self.status_var.set("Making slow-motion video...")
        self.video_button.configure(state=tk.DISABLED)
        self.video_thread = threading.Thread(
            target=self._video_worker, args=(Path(source),), daemon=True
        )
        self.video_thread.start()

    def _video_worker(self, source):
        def progress(done, total):
            self.output_queue.put(("STATUS", f"Making video... {done}/{total}"))

        try:
            result = make_video.make_video(source, progress=progress)
            self.output_queue.put(("VIDEO_DONE", result))
        except Exception as exc:
            self.output_queue.put(("VIDEO_ERROR", str(exc)))

    def _on_video_done(self, result):
        self.video_button.configure(state=tk.NORMAL)
        w, h = result["size"]
        self._append_log(
            "Slow-motion video saved.\n"
            f"  Frames:   {result['frame_count']} @ {result['fps']} fps playback\n"
            f"  Size:     {w}x{h}\n"
            f"  Saved to: {result['out_path']}\n"
        )
        self.status_var.set(f"Video saved: {Path(result['out_path']).name}")
        self.last_output_dir = Path(result["out_path"]).parent
        # End of the auto chain: start the next queued monitor event, if any.
        self._pump_monitor_chain()

    def _on_video_error(self, payload):
        self.status_var.set(f"Video: {payload}")
        self._append_log(f"[Video Error] {payload}\n")
        self.video_button.configure(state=tk.NORMAL)
        # End of the auto chain: start the next queued monitor event, if any.
        self._pump_monitor_chain()
