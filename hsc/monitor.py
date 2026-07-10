#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Online (streaming) injection detection for Monitor mode.

The engine is fed one frame at a time and finds injection events with the
SAME numbers the offline detector uses: the per-frame changed-pixel count
(``DIFF_THRESH``) triggers at ``detect_bounds_with_presence``'s ``min_peak``,
the onset is refined by the same walk-left, and the end uses the same
downsampled jet-presence measurement. The one online-specific criterion is
the end rule: offline knows the post-jet trough in advance; online we declare
the end when the smoothed presence falls below ``MON_END_FRAC`` of the
event's own presence peak and stays there for ``END_HOLD`` frames. The
replay harness (``uv run python -m hsc.monitor <burst> --compare``)
validates this against the offline detector on real bursts.

Pure NumPy -- no SDK, no Tk -- so every path is unit-testable headless.
"""

from collections import deque

import numpy as np

from hsc import injection_extract as ie

# Trigger = the offline detector's min_peak (an injection exists only if some
# frame changes at least this many full-resolution pixels).
MON_TRIGGER = 300.0
# Online end rule: presence has dropped for good when its moving average falls
# below this fraction of the event's presence peak (validated by replay).
MON_END_FRAC = 0.25
MON_END_ABS = 2.0            # ...or below this absolute count, whichever is larger


class MonitorEngine:
    """Streaming state machine: armed -> recording -> padding -> armed."""

    def __init__(self, before=30, after=30, trigger=None,
                 max_event_frames=3000, walkback=60):
        self.before = int(before)
        self.after = int(after)
        self.trigger = float(MON_TRIGGER if trigger is None else trigger)
        self.max_event_frames = int(max_event_frames)
        self.walkback = int(walkback)
        keep = self.before + self.walkback
        self._ring = deque(maxlen=keep)          # pre-trigger frames (uint8)
        self._sig_ring = deque(maxlen=keep)      # their motion counts
        self._prev = None                        # previous frame as int16
        self._fed = 0
        self._events = 0
        self._state = "armed"
        self._reset_event()

    # -- public ------------------------------------------------------------
    @property
    def stats(self):
        return {"fed": self._fed, "events": self._events, "state": self._state}

    def feed(self, frame_u8):
        """Feed one grayscale frame; returns a MonitorEvent dict when one closes."""
        frame_u8 = np.ascontiguousarray(frame_u8, dtype=np.uint8)
        pixels = frame_u8.astype(np.int16)
        if self._prev is not None and self._prev.shape == pixels.shape:
            count = float(np.count_nonzero(
                np.abs(pixels - self._prev) > ie.DIFF_THRESH))
        else:
            count = 0.0
        self._prev = pixels
        self._fed += 1

        if self._state == "armed":
            if count > self.trigger:
                self._begin_event(frame_u8, count)
            else:
                self._ring.append(frame_u8)
                self._sig_ring.append(count)
            return None

        # recording / padding
        self._ev_frames.append(frame_u8)
        self._ev_signal.append(count)

        if self._state == "recording":
            self._update_presence(frame_u8)
            if len(self._ev_frames) >= self.max_event_frames:
                self._end_idx = len(self._ev_frames) - 1
                self._dropped_note = (
                    f"runaway cap: event truncated at {self.max_event_frames} frames")
                self._state = "padding"
            elif self._presence_ended():
                self._end_idx = self._end_at
                self._state = "padding"
            if self._state == "padding" and self.after == 0:
                return self._close_event()
            return None

        # padding
        self._pad_got += 1
        if self._pad_got >= self.after:
            return self._close_event()
        return None

    def flush(self):
        """Close any in-flight event (user stopped monitoring mid-jet)."""
        if self._state == "armed" or not self._ev_frames:
            return None
        if self._end_idx is None:
            self._end_idx = len(self._ev_frames) - 1
        return self._close_event()

    # -- internals -----------------------------------------------------------
    def _reset_event(self):
        self._pre_frames = []
        self._pre_signal = []
        self._ev_frames = []
        self._ev_signal = []
        self._first_ev_fed = 0        # global index (0-based) of first event frame
        self._bg = None
        self._mask = None
        self._presence = deque(maxlen=ie.END_SMOOTH_WIN)
        self._presence_max = 0.0
        self._low_run = 0
        self._end_idx = None
        self._end_at = None
        self._pad_got = 0
        self._dropped_note = ""

    def _begin_event(self, frame_u8, count):
        self._reset_event()
        self._pre_frames = list(self._ring)
        self._pre_signal = list(self._sig_ring)
        self._ring.clear()
        self._sig_ring.clear()
        self._first_ev_fed = self._fed - 1            # this frame, 0-based
        self._ev_frames = [frame_u8]
        self._ev_signal = [count]
        ds = ie.DOWNSAMPLE
        if self._pre_frames:
            stack = np.stack([f[::ds, ::ds].astype(np.int16)
                              for f in self._pre_frames])
            self._bg = np.median(stack, axis=0)
        else:
            self._bg = np.zeros_like(frame_u8[::ds, ::ds], dtype=np.float64)
        small = frame_u8[::ds, ::ds].astype(np.int16)
        self._mask = np.abs(small - self._bg) > ie.MASK_DIFF
        if int(self._mask.sum()) < 10:                # degenerate: whole frame
            self._mask = np.ones_like(self._mask)
        self._state = "recording"
        self._update_presence(frame_u8)

    def _update_presence(self, frame_u8):
        ds = ie.DOWNSAMPLE
        small = frame_u8[::ds, ::ds].astype(np.int16)
        p = float(np.count_nonzero(
            (np.abs(small - self._bg) > ie.PRESENCE_DIFF) & self._mask))
        self._presence.append(p)
        smooth = float(np.mean(self._presence))
        self._presence_max = max(self._presence_max, smooth)
        low = smooth <= max(MON_END_ABS, MON_END_FRAC * self._presence_max)
        if low and len(self._ev_frames) > ie.END_MIN_GAP:
            self._low_run += 1
            if self._low_run == 1:
                self._end_at = len(self._ev_frames) - 1
        else:
            self._low_run = 0
            self._end_at = None

    def _presence_ended(self):
        return self._low_run >= ie.END_HOLD and self._end_at is not None

    def _close_event(self):
        seq_frames = self._pre_frames + self._ev_frames
        seq_signal = self._pre_signal + self._ev_signal
        n = len(seq_frames)
        n_pre = len(self._pre_frames)
        # Onset: walk left from the trigger frame over the recorded signal,
        # same thresholds as detect_injection_bounds' walk.
        trig_val = self._ev_signal[0]
        thr = max(30.0, 0.005 * trig_val)
        start = n_pre
        i, miss = n_pre - 1, 0
        while i >= 0:
            if seq_signal[i] > thr:
                start, miss = i, 0
            else:
                miss += 1
                if miss > 5:
                    break
            i -= 1
        end = n_pre + self._end_idx
        peak = int(np.argmax(np.asarray(seq_signal)))
        copy_start = max(0, start - self.before)
        copy_end = min(n - 1, end + self.after)
        # Names come from the GLOBAL frame counter (1-based), so files are
        # traceable to the monitoring timeline across events.
        first_seq_fed = self._first_ev_fed - n_pre
        seq_names = [f"frame_{first_seq_fed + k + 1:06d}.bmp" for k in range(n)]
        event = {
            "frames": seq_frames[copy_start : copy_end + 1],
            "names": seq_names[copy_start : copy_end + 1],
            "seq_names": seq_names,
            "seq_signal": list(seq_signal),
            "bounds": (start, end, peak),
            "window": (copy_start, copy_end),
            "fed_index": self._fed,
            "dropped_note": self._dropped_note,
        }
        self._events += 1
        self._state = "armed"
        self._reset_event()
        # The frame that closed the event is gone from the ring (it was an
        # event frame); the next armed frame re-seeds it naturally.
        return event
