#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Background writer for Monitor-mode events.

Encodes the BMPs itself with cv2 (8-bit grayscale -- no camera SDK needed),
on its own thread, so the grab loop never pauses while an event is written.
Errors are reported through the callback, never raised into the grab thread.
"""

import json
import queue
import threading
from pathlib import Path

import cv2


class EventWriter:
    def __init__(self, on_done):
        self._on_done = on_done
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, dest_dir, names, frames, meta):
        self._q.put((str(dest_dir), list(names), list(frames), dict(meta)))

    def close(self, timeout=30):
        self._q.put(None)
        self._thread.join(timeout)

    def _run(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            dest_dir, names, frames, meta = item
            try:
                dest = Path(dest_dir)
                dest.mkdir(parents=True, exist_ok=True)
                for nm, frame in zip(names, frames):
                    if not cv2.imwrite(str(dest / nm), frame):
                        raise OSError(f"cv2.imwrite failed for {nm}")
                if meta:
                    (dest / "injection_meta.json").write_text(
                        json.dumps(meta, indent=2), encoding="utf-8")
                self._on_done(dest_dir, True,
                              f"saved {len(names)} frames")
            except Exception as exc:            # report, never crash the thread
                self._on_done(dest_dir, False, str(exc))
