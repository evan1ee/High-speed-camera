#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Online (streaming) injection detection for Monitor mode.

The engine is fed one frame at a time and finds injection events from the
same per-frame changed-pixel count the offline detector uses (its
``DIFF_THRESH`` / ``min_peak`` numbers). An event triggers when the count
exceeds ``MON_TRIGGER``; the onset is refined by the offline walk-left; the
end fires when the count stays *quiet* -- at or below
``max(MON_END_ABS, MON_END_FRAC x event peak)`` (the offline walk's own
thresholds) -- for ``MON_END_HOLD`` consecutive frames.

Design notes from the 2026-07-10 on-rig session (root-cause of v1's failure):

* No presence-vs-background end rule. The first version compared each frame
  against a pre-trigger background median (like the offline end detector),
  but ONLINE that background is unfixably stale: the injection wets/mists the
  scene, every later frame differs from the dry background forever, and the
  end never fired (every event ran into the runaway cap). The offline
  detector escapes this only because it can scan ahead and set its threshold
  from the post-jet trough. The temporal signal needs no background: on this
  rig an active jet changes hundreds..thousands of pixels per frame while the
  wet-but-static scene changes ~0-25, measured on the saved runaway events.
* ``MON_END_HOLD`` is much longer than the offline walk's ``gap`` (5) because
  the burst phase has brief lulls (a 25-frame quiet stretch occurred inside a
  real injection) that a short hold would mistake for the end.
* ``MON_MIN_PEAK`` validation at close: drips/mist also trip the 300-pixel
  trigger, but real injections peak at 6k..55k changed pixels (measured over
  25 recorded bursts) while the junk events peaked at <=760. Events whose
  peak stays below ``MON_MIN_PEAK`` are returned with ``discarded`` set and
  must not be saved.
* Detection watches only the left ``MON_DETECT_FRAC`` (2/3) of the columns:
  the nozzle is at the right edge and gets removed/reinstalled between
  injections while monitoring runs -- that hand/tool churn must not trigger.
  Saved frames are always the full width.

Pure NumPy -- no SDK, no Tk -- so every path is unit-testable headless.
Validation tool: ``uv run python -m hsc.monitor <burst> --compare`` replays a
recorded burst and checks the online events against the offline detector.
"""

from collections import deque

import numpy as np

from hsc import injection_extract as ie

# Trigger = the offline detector's min_peak floor (an event starts when one
# frame changes at least this many full-resolution pixels).
MON_TRIGGER = 300.0
# A closed event is real only if some frame changed at least this many pixels:
# junk (drips/mist) peaked <=760, the weakest real injection 5977 (data above).
MON_MIN_PEAK = 3000.0
# Online end rule: the jet is over when the changed-pixel count stays at or
# below max(MON_END_ABS, MON_END_FRAC * event peak) -- the same abs_floor /
# frac numbers the offline walk uses -- for MON_END_HOLD consecutive frames.
MON_END_ABS = 30.0
MON_END_FRAC = 0.005
MON_END_HOLD = 60
# The decaying jet tail stays faintly VISIBLE for a couple dozen frames after
# it stops changing pixels (offline presence-end lags the motion-quiet point
# by 24-27 frames on real bursts), so the recorded end is pushed this far into
# the quiet hold. The frames already sit in RAM (MON_END_HOLD > margin).
MON_END_MARGIN = 30
# Only the left fraction of the columns feeds detection: the nozzle sits at
# the RIGHT edge and is removed/reinstalled between injections while
# monitoring runs, churning pixels there. The jet spans leftward across the
# frame, so cropping to 2/3 keeps real peaks (6k..55k full-frame) comfortably
# above MON_MIN_PEAK. Full frames are still recorded and saved.
MON_DETECT_FRAC = 2.0 / 3.0


class MonitorEngine:
    """Streaming state machine: armed -> recording -> padding -> armed."""

    def __init__(self, before=30, after=30, trigger=None,
                 max_event_frames=600, walkback=60, min_peak=None,
                 detect_frac=None):
        self.before = int(before)
        self.after = int(after)
        self.trigger = float(MON_TRIGGER if trigger is None else trigger)
        self.min_peak = float(MON_MIN_PEAK if min_peak is None else min_peak)
        self.detect_frac = float(
            MON_DETECT_FRAC if detect_frac is None else detect_frac)
        self.max_event_frames = int(max_event_frames)
        self.walkback = int(walkback)
        keep = self.before + self.walkback
        self._ring = deque(maxlen=keep)          # pre-trigger frames (uint8)
        self._sig_ring = deque(maxlen=keep)      # their motion counts
        self._prev = None                        # previous frame as int16
        self._fed = 0
        self._events = 0
        self._discarded = 0
        self._state = "armed"
        self._reset_event()

    # -- public ------------------------------------------------------------
    @property
    def stats(self):
        return {"fed": self._fed, "events": self._events,
                "discarded": self._discarded, "state": self._state}

    def feed(self, frame_u8):
        """Feed one grayscale frame; returns a MonitorEvent dict when one closes.

        A closed event with a non-empty ``discarded`` field failed the
        ``min_peak`` validation (drip/mist trigger) and must not be saved.
        """
        frame_u8 = np.ascontiguousarray(frame_u8, dtype=np.uint8)
        pixels = frame_u8.astype(np.int16)
        if self._prev is not None and self._prev.shape == pixels.shape:
            w_det = max(1, int(round(pixels.shape[1] * self.detect_frac)))
            count = float(np.count_nonzero(
                np.abs(pixels[:, :w_det] - self._prev[:, :w_det])
                > ie.DIFF_THRESH))
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
            self._ev_peak = max(self._ev_peak, count)
            self._update_quiet(count)
            if len(self._ev_frames) >= self.max_event_frames:
                self._end_idx = len(self._ev_frames) - 1
                self._dropped_note = (
                    f"runaway cap: event truncated at {self.max_event_frames} frames")
            elif self._quiet_run >= MON_END_HOLD and self._end_at is not None:
                self._end_idx = min(len(self._ev_frames) - 1,
                                    self._end_at + MON_END_MARGIN)
            if self._end_idx is None:
                return None
            # End found: the quiet-hold tail may already cover the `after`
            # padding; otherwise keep collecting in the padding state.
            tail = len(self._ev_frames) - 1 - self._end_idx
            if tail >= self.after:
                return self._close_event()
            self._state = "padding"
            self._pad_got = tail
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
        self._ev_peak = 0.0
        self._quiet_run = 0
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
        self._ev_peak = count
        self._state = "recording"

    def _update_quiet(self, count):
        quiet = count <= max(MON_END_ABS, MON_END_FRAC * self._ev_peak)
        if quiet and len(self._ev_frames) > ie.END_MIN_GAP:
            self._quiet_run += 1
            if self._quiet_run == 1:
                self._end_at = len(self._ev_frames) - 1
        else:
            self._quiet_run = 0
            self._end_at = None

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
        discarded = ""
        if self._ev_peak < self.min_peak:
            discarded = (f"low peak: {self._ev_peak:.0f} changed px "
                         f"< min_peak {self.min_peak:.0f} (drip/mist trigger)")
        event = {
            "frames": seq_frames[copy_start : copy_end + 1],
            "names": seq_names[copy_start : copy_end + 1],
            "seq_names": seq_names,
            "seq_signal": list(seq_signal),
            "bounds": (start, end, peak),
            "window": (copy_start, copy_end),
            "fed_index": self._fed,
            "dropped_note": self._dropped_note,
            "discarded": discarded,
        }
        if discarded:
            self._discarded += 1
        else:
            self._events += 1
        self._state = "armed"
        self._reset_event()
        # The frame that closed the event is gone from the ring (it was an
        # event frame); the next armed frame re-seeds it naturally.
        return event


def replay(source_dir, before=30, after=30, trigger=None, min_peak=None,
           keep_discarded=False):
    """Feed a recorded burst through a fresh engine; return the closed events.

    Discarded (low-peak) events are dropped unless *keep_discarded* is set.
    """
    from hsc import measure_angle  # load_gray fast BMP path, no cv2 decode

    files = ie.list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")
    eng = MonitorEngine(before=before, after=after, trigger=trigger,
                        min_peak=min_peak)
    events = []
    for f in files:
        ev = eng.feed(measure_angle.load_gray(f))
        if ev:
            events.append(ev)
    tail = eng.flush()
    if tail:
        events.append(tail)
    if not keep_discarded:
        events = [ev for ev in events if not ev["discarded"]]
    return events


def _main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Replay Monitor-mode detection on a recorded burst.")
    parser.add_argument("source")
    parser.add_argument("--before", type=int, default=30)
    parser.add_argument("--after", type=int, default=30)
    parser.add_argument("--min-peak", type=float, default=None,
                        help=f"validation threshold (default {MON_MIN_PEAK:.0f})")
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()

    events = replay(args.source, args.before, args.after,
                    min_peak=args.min_peak, keep_discarded=True)
    kept = [ev for ev in events if not ev["discarded"]]
    print(f"{len(kept)} event(s) detected online"
          + (f" (+{len(events) - len(kept)} discarded)" if len(events) != len(kept) else ""))
    for k, ev in enumerate(events, 1):
        extra = ""
        if ev["dropped_note"]:
            extra += f" [{ev['dropped_note']}]"
        if ev["discarded"]:
            extra += f" [DISCARDED: {ev['discarded']}]"
        print(f"  event {k}: kept {ev['names'][0]} .. {ev['names'][-1]} "
              f"({len(ev['names'])} frames){extra}")
    if args.compare:
        # Name-parsing note: [6:12] slices the six digits of frame_XXXXXX.bmp;
        # keep the naming format in _close_event and this parse in sync.
        files = ie.list_frames(args.source)
        signal, _ = ie.compute_motion_signal_best(files)
        getter = ie.raw_downsample_getter(files)
        off = ie.detect_bounds_with_presence(np.asarray(signal), getter, len(files))
        if off is None:
            print("offline: no injection detected")
            return
        start, end, _ = off
        print(f"offline: frames {files[start].name} .. {files[end].name}")
        if kept:
            # The offline detector reports exactly one window per burst; the
            # gate passes when ANY kept online event's saved window covers the
            # offline injection (start..end). The before-padding itself is not
            # gated: a discarded pre-disturbance can legitimately sit there.
            ok = any(
                int(ev["names"][0][6:12]) - 1 <= start
                and int(ev["names"][-1][6:12]) - 1 >= end
                for ev in kept
            )
            print("OK: an online event covers the offline window" if ok
                  else "MISMATCH: no online event covers the offline window")
        else:
            print("MISMATCH: offline found an injection, online kept none")


if __name__ == "__main__":
    _main()
