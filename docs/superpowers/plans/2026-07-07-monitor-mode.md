# Monitor Mode (continuous multi-injection capture) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Updated 2026-07-10** against the current codebase: the GUI is now the `hsc/gui/` mixin
> package (not `hsc/capture_gui.py`), `hsc/smart_save.py` has landed (prerequisite met), the
> auto chain order is now **measure → video** (video last, outside the timed span), and
> settings live in `settings\` at the repo root. User decisions (interview 2026-07-10):
> camera-owning buttons are disabled while monitoring; overlapping events are queued and
> processed in order; Stop mid-jet saves AND processes the partial event.

**Goal:** A **Start Monitoring / Stop Monitoring** toggle: the camera streams continuously, every injection is detected online and saved automatically to its own `data\injection images\monitor_<stamp>` folder (then chained through measure + video), and the rig keeps waiting for the next injection — no Capture click per shot.

**Architecture:** Three cleanly separated layers. (1) `hsc/monitor.py` — a pure, camera-free `MonitorEngine` state machine (`armed → recording → padding → armed`) fed one frame at a time; it holds a bounded pre-trigger ring buffer and reuses the existing detection constants. (2) `hsc/frame_writer.py` — a background writer thread that encodes BMPs itself (no SDK), so grabbing never pauses while an event is being written. (3) A thin GUI layer split per the `hsc/gui/` recipe: a new `MonitorMixin` (`hsc/gui/monitor.py`) owns the button/queue-handler/chain-pump UI side, and `_do_monitor` in `hsc/gui/camera_worker.py` runs the grab loop, dispatched from `_camera_worker`'s request ladder exactly like `_do_capture`. All heavy logic is unit-testable headless; a replay harness proves the online detector finds the same windows as the offline one on recorded bursts.

**Tech Stack:** Python 3.13 via uv, NumPy/OpenCV (locked), pytest. No new dependencies. No camera needed for any test.

## PREREQUISITE — met

`hsc/smart_save.py` exists with `plan_window`, `make_result`, `make_meta`, `write_meta`, `replay` (verified 2026-07-10). Monitor mode reuses `make_result`/`make_meta` verbatim.

## Global Constraints

- Branch `monitor-mode` off `main`; conventional commits, one per task; run everything from the repo root `D:\01_Data\code\spray-angle-test\High speed camera` (quote it — spaces); tests via `uv run python -m pytest`; the full existing suite stays green after every task.
- **Detection numbers are not new**: the trigger threshold and all end-detection constants come from `hsc/injection_extract.py` — verified present: `DIFF_THRESH=25` (line 50), `DOWNSAMPLE=4` (56), `PRESENCE_DIFF=25` (57), `MASK_DIFF=40` (58), `END_SMOOTH_WIN=21` (60), `END_HOLD=25` (61), `END_MIN_GAP=8` (62), and `detect_bounds_with_presence`'s defaults (`min_peak=300`, `abs_floor=30.0`, `frac=0.005`, `gap=5` via `detect_injection_bounds`). Do not change any of them. The ONE new tunable is `MON_END_FRAC` (online end criterion — see Task 1), validated by the Task 2 replay gate.
- **The grab hot path stays minimal**: inside `_do_monitor`'s loop, per frame do only grab → `np.frombuffer` copy → release SDK frame → `engine.feed` → (throttled) preview. No disk I/O, no BMP encoding, no SDK save calls in that loop. (The one `mkdir` per *event close* in `_dispatch_monitor_event` is fine — events are rare.)
- **Bounded memory**: the engine may never hold more than `before + walkback + max_event_frames + after` frames (~250 MB worst case at 320×240 with the defaults; typically ~30 MB). Enforced by `deque(maxlen=...)` and the runaway cap, and asserted by test.
- **No Tk variable reads on the camera thread**: `_toggle_monitor` (UI thread) snapshots `before_var`/`after_var` into `self.monitor_params` (a `SimpleNamespace`, same pattern as `capture_params`); `_do_monitor` reads only that.
- GUI contracts preserved: existing buttons/flows untouched except the listed insertion points; new queue message kinds only (`MONITOR_EVENT`, `MONITOR_SAVED`, `MONITOR_STOPPED`), registered via the mixin's `QUEUE_HANDLERS` dict (the app merges them in `_collect_queue_handlers`; duplicate kinds raise at startup). The preview-queue `STOPPED` handler in `hsc/gui/capture.py` must also reset monitor state (same pattern as the existing stranded-still-request reset).
- Monitor mode is **additive and opt-in**; nothing changes unless the user clicks the new button.
- The Tk GUI and live camera cannot run headless: Task 4 is verified by `py_compile`, the wiring tests, and review; Task 5's on-rig checklist is the real gate. Reports must say so honestly.
- Camera safety note for docs (Task 5): continuous streaming is the sensor's designed duty cycle (the preview already streams continuously); no mechanical parts; only heat matters — keep the camera ventilated.

---

### Task 1: `hsc/monitor.py` — the online detection engine

**Files:**
- Create: `hsc/monitor.py`
- Test: `tests/test_monitor_engine.py`

**Interfaces (consumed by Tasks 2–4):**
- `MonitorEngine(before=30, after=30, trigger=None, max_event_frames=3000, walkback=60)`
- `engine.feed(frame_u8) -> MonitorEvent | None` — returns a completed event exactly once, when it closes.
- `engine.flush() -> MonitorEvent | None` — closes any in-flight event (user pressed Stop mid-jet).
- `MonitorEvent` (dict): `frames` (list of uint8 arrays — the save window only), `names` (parallel BMP filenames from the global frame counter), `seq_names`/`seq_signal` (full internal sequence, for `make_result`), `bounds` (start, end, peak — indices into the internal sequence), `window` (copy_start, copy_end — same clamp math as `build_result`), `fed_index` (global frame count at close), `dropped_note` (str, empty unless the runaway cap fired).
- `engine.stats` — dict with `fed`, `events`, `state`.

**End-of-event timing note (why the test streams are long):** with the real constants the
presence signal is smoothed over `END_SMOOTH_WIN=21` frames and must stay low for
`END_HOLD=25` frames, so an event closes ~16+25+after frames AFTER the jet visually vanishes.
Synthetic streams must extend well past the jet end or the event only closes on `flush()`.

- [ ] **Step 1: Write the failing tests** (`tests/test_monitor_engine.py`)

```python
"""MonitorEngine: online trigger, presence-based end, ring buffer, padding."""
import numpy as np

from hsc import injection_extract
from hsc.monitor import MonitorEngine


W, H = 160, 120


def _scene():
    return np.full((H, W), 15, np.uint8)


def _jet():
    f = _scene()
    f[55:65, 20:60] = 220          # 400 px change on appearance > trigger 300
    return f


def _stream(events, n_total):
    """Frame stream: `events` is a list of (onset, end) index pairs."""
    for i in range(n_total):
        yield _jet() if any(a <= i < b for a, b in events) else _scene()


def test_single_event_window():
    eng = MonitorEngine(before=5, after=7)
    got = []
    # Jet on frames 40..69; presence smoothing (END_SMOOTH_WIN=21) + END_HOLD=25
    # means the end confirms around frame ~111 and the event closes ~118, so the
    # stream must run well past that.
    for i, f in enumerate(_stream([(40, 70)], 160)):
        ev = eng.feed(f)
        if ev is not None:
            got.append((i, ev))
    assert len(got) == 1
    closed_at, ev = got[0]
    start, end, peak = ev["bounds"]
    seq_onset_frame = ev["seq_names"][start]
    # The onset frame must be the global frame 40 (named by the global counter).
    assert seq_onset_frame == "frame_000041.bmp"     # 1-based naming
    # Window = onset-before .. end+after, and frames/names align.
    assert ev["window"][0] == max(0, start - 5)
    assert len(ev["frames"]) == len(ev["names"]) == ev["window"][1] - ev["window"][0] + 1
    # End must be at/after the jet vanished (frame 70) and the event must close
    # only after the `after` padding.
    assert ev["seq_names"][end] >= "frame_000070.bmp"
    assert closed_at >= 70 + 7 - 1


def test_no_event_on_static_scene_and_memory_bounded():
    eng = MonitorEngine(before=5, after=7)
    for f in _stream([], 500):
        assert eng.feed(f) is None
    assert eng.stats["events"] == 0
    assert eng.stats["state"] == "armed"
    # Ring buffers are bounded regardless of how long we monitor.
    assert len(eng._ring) <= 5 + eng.walkback


def test_two_events_both_detected():
    eng = MonitorEngine(before=5, after=5)
    events = []
    # Event 1 (30..59) closes ~106; event 2 fires at 200 with plenty of armed
    # gap, ends 230, closes ~276. Stream to 320 to cover both closures.
    for f in _stream([(30, 60), (200, 230)], 320):
        ev = eng.feed(f)
        if ev:
            events.append(ev)
    assert len(events) == 2
    assert events[0]["seq_names"][events[0]["bounds"][0]] == "frame_000031.bmp"
    assert events[1]["seq_names"][events[1]["bounds"][0]] == "frame_000201.bmp"


def test_runaway_cap_closes_a_never_ending_jet():
    eng = MonitorEngine(before=5, after=5, max_event_frames=50)
    ev = None
    for f in _stream([(10, 10_000)], 200):
        ev = eng.feed(f) or ev
    assert ev is not None
    assert ev["dropped_note"] != ""          # cap fired, honestly recorded


def test_flush_returns_partial_event():
    eng = MonitorEngine(before=5, after=5)
    for f in _stream([(20, 10_000)], 40):    # stop mid-jet
        eng.feed(f)
    ev = eng.flush()
    assert ev is not None and len(ev["frames"]) > 0
    assert eng.flush() is None               # idempotent


def test_feed_meets_perf_budget():
    import time
    eng = MonitorEngine(before=30, after=30)
    frames = [f for f in _stream([(100, 160)], 400)]
    big = [np.kron(f, np.ones((2, 2), np.uint8)) for f in frames]  # 320x240
    t0 = time.perf_counter()
    for f in big:
        eng.feed(f)
    per_frame = (time.perf_counter() - t0) / len(big)
    assert per_frame < 0.0015, f"feed averaged {per_frame * 1e3:.2f} ms/frame"
```

- [ ] **Step 2: Run — must fail** (`uv run python -m pytest tests/test_monitor_engine.py -v` → ModuleNotFoundError)

- [ ] **Step 3: Implement `hsc/monitor.py`**

```python
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
event's own presence peak and stays there for ``END_HOLD`` frames. The Task-2
replay harness validates this against the offline detector on real bursts.

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
```

Implementation notes the implementer must honor: (1) the constant names `DIFF_THRESH`, `DOWNSAMPLE`, `MASK_DIFF`, `PRESENCE_DIFF`, `END_SMOOTH_WIN`, `END_MIN_GAP`, `END_HOLD` were all verified to exist in `hsc/injection_extract.py` on 2026-07-10 (lines 50–62); (2) `test_single_event_window`'s naming assertion pins the global-counter convention — if your indexing is off by one, fix the code, not the test, until the onset frame is the frame that actually changed; (3) keep `feed` allocation-light (the perf test enforces it).

- [ ] **Step 4: Run the tests** — all 6 PASS. Full suite: `uv run python -m pytest -q` → green.

- [ ] **Step 5: Commit**

```bash
git add hsc/monitor.py tests/test_monitor_engine.py
git commit -m "feat: streaming MonitorEngine for continuous injection detection"
```

---

### Task 2: Replay harness — prove the online engine matches the offline detector

**Files:**
- Modify: `hsc/monitor.py` (add `replay()` + `__main__`)
- Test: `tests/test_monitor_replay.py`

**Interfaces:**
- `monitor.replay(source_dir, before=30, after=30) -> list[dict]` — feeds a recorded burst's frames through a fresh `MonitorEngine` (flushing at the end) and returns the events with their kept-frame names.
- CLI: `uv run python -m hsc.monitor "data\captures\<run>" --compare` — prints each event's window and the offline `detect_bounds_with_presence` window side by side, with an `OK` / `MISMATCH` verdict per the tolerance below.

(APIs used, all verified present in `hsc/injection_extract.py`: `list_frames`, `compute_motion_signal_best` → `(signal, method)`, `raw_downsample_getter`, `detect_bounds_with_presence(signal, getter, n)`; and `measure_angle.load_gray` at `hsc/measure_angle.py:209`.)

- [ ] **Step 1: Failing test** (`tests/test_monitor_replay.py`)

```python
"""Replaying a recorded burst online must find the offline detector's event."""
import cv2
import numpy as np

from hsc import injection_extract, monitor


def _write_burst(folder, n=120, onset=40, end=90, w=160, h=120):
    folder.mkdir(parents=True)
    scene = np.full((h, w), 15, np.uint8)
    jet = scene.copy()
    jet[55:65, 20:60] = 220
    for i in range(n):
        cv2.imwrite(str(folder / f"frame_{i + 1:06d}.bmp"),
                    jet if onset <= i < end else scene)


def test_replay_agrees_with_offline_detector(tmp_path):
    src = tmp_path / "burst"
    _write_burst(src)
    events = monitor.replay(src, before=5, after=7)
    assert len(events) == 1
    ev = events[0]

    files = injection_extract.list_frames(src)
    signal, _ = injection_extract.compute_motion_signal_best(files)
    getter = injection_extract.raw_downsample_getter(files)
    off = injection_extract.detect_bounds_with_presence(
        np.asarray(signal), getter, len(files))
    assert off is not None
    off_start, off_end, _ = off

    # Tolerance gate: onset within the walk gap; end may differ because the
    # online rule cannot see the future trough -- but the SAVED window must
    # fully cover the offline injection core.
    kept_first = int(ev["names"][0][6:12]) - 1
    kept_last = int(ev["names"][-1][6:12]) - 1
    assert abs((kept_first + 5) - off_start) <= 5       # onset agreement
    assert kept_first <= max(0, off_start - 5)          # covers before-padding
    assert kept_last >= off_end                          # covers the full jet
    assert kept_last <= off_end + 7 + 60                 # doesn't run away
```

- [ ] **Step 2: Run — fail** (no `replay`).

- [ ] **Step 3: Implement** — append to `hsc/monitor.py`:

```python
def replay(source_dir, before=30, after=30, trigger=None):
    """Feed a recorded burst through a fresh engine; return the closed events."""
    from hsc import measure_angle  # load_gray fast BMP path, no cv2 decode

    files = ie.list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")
    eng = MonitorEngine(before=before, after=after, trigger=trigger)
    events = []
    for f in files:
        ev = eng.feed(measure_angle.load_gray(f))
        if ev:
            events.append(ev)
    tail = eng.flush()
    if tail:
        events.append(tail)
    return events


def _main():
    import argparse

    import numpy as np

    parser = argparse.ArgumentParser(
        description="Replay Monitor-mode detection on a recorded burst.")
    parser.add_argument("source")
    parser.add_argument("--before", type=int, default=30)
    parser.add_argument("--after", type=int, default=30)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()

    events = replay(args.source, args.before, args.after)
    print(f"{len(events)} event(s) detected online")
    for k, ev in enumerate(events, 1):
        print(f"  event {k}: kept {ev['names'][0]} .. {ev['names'][-1]} "
              f"({len(ev['names'])} frames){' [' + ev['dropped_note'] + ']' if ev['dropped_note'] else ''}")
    if args.compare:
        files = ie.list_frames(args.source)
        signal, _ = ie.compute_motion_signal_best(files)
        getter = ie.raw_downsample_getter(files)
        off = ie.detect_bounds_with_presence(np.asarray(signal), getter, len(files))
        if off is None:
            print("offline: no injection detected")
            return
        start, end, _ = off
        print(f"offline: frames {files[start].name} .. {files[end].name}")
        if events:
            first = int(events[0]["names"][0][6:12]) - 1
            last = int(events[0]["names"][-1][6:12]) - 1
            ok = (first <= max(0, start - args.before)
                  and last >= end)
            print("OK: online window covers the offline event" if ok
                  else "MISMATCH: online window does not cover the offline event")


if __name__ == "__main__":
    _main()
```

(The name-parsing `[6:12]` slices the six digits of `frame_XXXXXX.bmp`; keep the naming format and this parse in sync.)

- [ ] **Step 4: Run** — test PASS; full suite green. Then, if any real bursts exist: for each folder in `data/captures/`, run `uv run python -m hsc.monitor "data/captures/<run>" --compare` → expect `OK`. Record outputs in the report (skip gracefully if none — the user cleans captures/). **If a real burst reports MISMATCH, tune `MON_END_FRAC` (0.25 → 0.15/0.35) until all real bursts pass, and record the chosen value + evidence — this is the plan's one calibration point.**

- [ ] **Step 5: Commit**

```bash
git add hsc/monitor.py tests/test_monitor_replay.py
git commit -m "feat: monitor replay harness validating online vs offline detection"
```

---

### Task 3: `hsc/frame_writer.py` — background event writer (no SDK)

**Files:**
- Create: `hsc/frame_writer.py`
- Test: `tests/test_frame_writer.py`

**Interfaces:**
- `EventWriter(on_done)` — `on_done(dest_dir: str, ok: bool, message: str)` is called from the writer thread after each event finishes (the GUI passes a closure that posts to `output_queue`).
- `writer.submit(dest_dir, names, frames, meta)` — queues one event; frames are uint8 arrays; `meta` (dict) is written as `injection_meta.json`.
- `writer.close(timeout=30)` — drains the queue and joins the thread.

- [ ] **Step 1: Failing tests** (`tests/test_frame_writer.py`)

```python
"""EventWriter: writes BMPs + meta in the background, reports completion."""
import json
import queue

import numpy as np

from hsc.frame_writer import EventWriter
from hsc import measure_angle


def _frames(n=5, w=64, h=48):
    return [np.full((h, w), 40 + i, np.uint8) for i in range(n)]


def test_writes_frames_and_meta(tmp_path):
    done = queue.Queue()
    w = EventWriter(lambda d, ok, msg: done.put((d, ok, msg)))
    dest = tmp_path / "ev1"
    frames = _frames()
    names = [f"frame_{i + 1:06d}.bmp" for i in range(len(frames))]
    meta = {"pre_frames": 2, "onset_index": 2, "copy_start": 0,
            "copy_end": 4, "method": "monitor"}
    w.submit(str(dest), names, frames, meta)
    d, ok, msg = done.get(timeout=10)
    w.close()
    assert ok and d == str(dest)
    for nm, f in zip(names, frames):
        back = measure_angle.load_gray(dest / nm)     # fast-BMP-path readable
        assert np.array_equal(back, f)
    assert json.loads((dest / "injection_meta.json").read_text()) == meta


def test_error_reported_not_raised(tmp_path):
    done = queue.Queue()
    w = EventWriter(lambda d, ok, msg: done.put((d, ok, msg)))
    bad = tmp_path / "file.txt"
    bad.write_text("in the way")
    w.submit(str(bad / "sub"), ["frame_000001.bmp"], _frames(1), {})
    d, ok, msg = done.get(timeout=10)
    w.close()
    assert not ok and msg


def test_multiple_events_in_order(tmp_path):
    done = queue.Queue()
    w = EventWriter(lambda d, ok, msg: done.put(d))
    for k in range(3):
        w.submit(str(tmp_path / f"ev{k}"), ["frame_000001.bmp"], _frames(1), {})
    order = [done.get(timeout=10) for _ in range(3)]
    w.close()
    assert order == [str(tmp_path / f"ev{k}") for k in range(3)]
```

- [ ] **Step 2: Run — fail.**

- [ ] **Step 3: Implement `hsc/frame_writer.py`**

```python
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
```

- [ ] **Step 4: Run** — 3 PASS; full suite green. (If `measure_angle.load_gray`'s fast raw-BMP path rejects cv2-written BMPs, that is a finding — the existing backend-equivalence test already writes BMPs with cv2, so it should not.)

- [ ] **Step 5: Commit**

```bash
git add hsc/frame_writer.py tests/test_frame_writer.py
git commit -m "feat: background BMP event writer for monitor mode"
```

---

### Task 4: GUI integration — `MonitorMixin` + `_do_monitor`

**Files:**
- Create: `hsc/gui/monitor.py` (the UI-side mixin, per the recipe in `hsc/gui/app.py`'s docstring)
- Modify: `hsc/gui/camera_worker.py` (dispatch branch in `_camera_worker` + `_do_monitor` + `_dispatch_monitor_event`)
- Modify: `hsc/gui/app.py` (add `MonitorMixin` to bases + `_init_monitor_state()` call)
- Modify: `hsc/gui/layout.py` (button in the `actions` grid)
- Modify: `hsc/gui/capture.py` (preview-queue `STOPPED` handler also resets monitor state)
- Modify: `hsc/gui/video.py` (`_on_video_done` / `_on_video_error` pump the monitor chain)
- Modify: `tests/test_gui_structure.py` (add the three MONITOR kinds to `expected`)
- Test: `tests/test_monitor_wiring.py`

**Interfaces:**
- Consumes: `MonitorEngine` (Task 1), `EventWriter` (Task 3), `smart_save.make_result`/`make_meta`, `injection_extract.make_dest_dir`, `INJECTION_DIR` from `hsc.gui.config`.
- Produces: queue kinds `MONITOR_EVENT` (payload = `make_result`-shaped dict), `MONITOR_SAVED` (payload = `(dest_dir, ok, msg)`), `MONITOR_STOPPED` (payload = summary str). Chain: `MONITOR_SAVED(ok)` → `_monitor_chain` FIFO → `_pump_monitor_chain` → `auto_measure_pending=True` + `_on_extract_done(result)` → measure → video → `_on_video_done`/`_on_video_error` re-pump. This reuses the existing measure→video chain unchanged (video last, per the current order).

- [ ] **Step 1: Failing wiring tests** (`tests/test_monitor_wiring.py`, display-free, in the style of `tests/test_smart_dispatch.py`)

```python
"""Wiring tests for MonitorMixin: event/save/stop handlers + the chain pump.

Binds the REAL methods onto a display-free stub, so regressions in the
save-before-process ordering or the one-event-at-a-time pump are caught
without a Tk root or a camera.
"""
from hsc.gui.monitor import MonitorMixin


class _FakeWidget:
    def __init__(self):
        self.configured = []

    def configure(self, **kwargs):
        self.configured.append(kwargs)


class _FakeVar:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _FakeThread:
    def __init__(self, alive):
        self._alive = alive

    def is_alive(self):
        return self._alive


class _Gui:
    """Exactly what the monitor handlers touch; real methods borrowed."""

    _on_monitor_event = MonitorMixin._on_monitor_event
    _on_monitor_saved = MonitorMixin._on_monitor_saved
    _on_monitor_stopped = MonitorMixin._on_monitor_stopped
    _pump_monitor_chain = MonitorMixin._pump_monitor_chain
    _reset_monitor_ui = MonitorMixin._reset_monitor_ui
    MONITOR_DISABLED_BUTTONS = ("run_button",)

    def __init__(self, busy=False):
        import threading
        self.status_var = _FakeVar()
        self.monitor_button = _FakeWidget()
        self.run_button = _FakeWidget()
        self.monitor_active = True
        self.monitor_stop = threading.Event()
        self.monitor_requested = threading.Event()
        self.auto_measure_pending = False
        self._pipeline_t0 = None
        self._monitor_results = {}
        self._monitor_chain = []
        self.extract_thread = None
        self.measure_thread = _FakeThread(busy)
        self.video_thread = None
        self.logged = []
        self.dispatched = []

    def _append_log(self, text):
        self.logged.append(text)

    def _on_extract_done(self, result):
        self.dispatched.append(result)


def _result(dest):
    return {"dest_dir": dest, "copy_start_frame": "frame_000001.bmp"}


def test_event_is_held_until_saved_ok_then_processed():
    g = _Gui()
    r = _result("inj/monitor_1")
    g._on_monitor_event(r)
    assert g.dispatched == [] and g._monitor_chain == []   # not yet on disk

    g._on_monitor_saved(("inj/monitor_1", True, "saved 42 frames"))
    assert g.dispatched == [r]                              # processed
    assert g.auto_measure_pending is True
    assert g._pipeline_t0 is not None


def test_failed_save_drops_the_event():
    g = _Gui()
    g._on_monitor_event(_result("inj/monitor_1"))
    g._on_monitor_saved(("inj/monitor_1", False, "disk full"))
    assert g.dispatched == [] and g._monitor_chain == []
    assert any("disk full" in t for t in g.logged)


def test_pump_queues_while_busy_and_is_fifo():
    g = _Gui(busy=True)
    for k in (1, 2):
        r = _result(f"inj/monitor_{k}")
        g._on_monitor_event(r)
        g._on_monitor_saved((r["dest_dir"], True, "saved"))
    assert g.dispatched == []                # measure thread busy: queued
    assert len(g._monitor_chain) == 2

    g.measure_thread = _FakeThread(False)    # chain step finished
    g._pump_monitor_chain()
    assert [r["dest_dir"] for r in g.dispatched] == ["inj/monitor_1"]
    g._pump_monitor_chain()                  # next VIDEO_DONE re-pump
    assert [r["dest_dir"] for r in g.dispatched] == ["inj/monitor_1",
                                                     "inj/monitor_2"]
    assert g._monitor_chain == []


def test_monitor_stopped_resets_ui_and_pumps():
    g = _Gui()
    g._monitor_chain.append(_result("inj/monitor_1"))
    g._on_monitor_stopped("Monitoring stopped: 1 injection(s), 999 frames examined.")
    assert g.monitor_active is False
    assert g.dispatched != []                # queued event still processed
    assert {"text": "Start Monitoring", "state": "normal"} in [
        {k: str(v) for k, v in c.items()} for c in g.monitor_button.configured
    ]


def test_reset_monitor_ui_is_idempotent():
    g = _Gui()
    g._reset_monitor_ui()
    g._reset_monitor_ui()
    assert g.monitor_active is False
    assert not g.monitor_stop.is_set() and not g.monitor_requested.is_set()
```

- [ ] **Step 2: Run — fail** (`uv run python -m pytest tests/test_monitor_wiring.py -v` → ModuleNotFoundError).

- [ ] **Step 3: Create `hsc/gui/monitor.py`**

```python
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
    )

    def _init_monitor_state(self):
        self.monitor_requested = threading.Event()
        self.monitor_stop = threading.Event()
        self.monitor_active = False
        self.monitor_params = None
        # Events detected but not yet confirmed written (keyed by dest_dir).
        self._monitor_results = {}
        # Events safely on disk, awaiting their measure -> video run (FIFO).
        self._monitor_chain = []

    # ------------------------------------------------------------------
    # Button
    # ------------------------------------------------------------------
    def _toggle_monitor(self):
        if self.monitor_active:
            self.monitor_stop.set()
            # Re-enabled by MONITOR_STOPPED once the worker confirms.
            self.monitor_button.configure(state=tk.DISABLED)
            return
        if self.capture_requested.is_set():
            self.status_var.set("Finish the capture first.")
            return
        try:
            before = max(0, int(self.before_var.get()))
            after = max(0, int(self.after_var.get()))
        except (ValueError, tk.TclError):
            before, after = 30, 30
        # Snapshot on the UI thread; the camera thread must not read Tk vars.
        self.monitor_params = SimpleNamespace(before=before, after=after)
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
    # Chain pump: one event at a time through measure -> video
    # ------------------------------------------------------------------
    def _pump_monitor_chain(self):
        """Start measure+video for the next saved event, if the chain is idle.

        Re-invoked from _on_video_done/_on_video_error (the end of the auto
        chain) so queued events are processed strictly one at a time.
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
```

- [ ] **Step 4: Camera side** — in `hsc/gui/camera_worker.py`:

Add imports at the top (after the existing `from hsc import smart_save`):

```python
from datetime import datetime

from hsc import frame_writer
from hsc import monitor
```

In `_camera_worker`'s request ladder, immediately AFTER the `capture_requested` block (after its `continue`, before the still-request block):

```python
                # Monitor mode: continuous grab + online injection detection,
                # until the user clicks Stop Monitoring.
                if self.monitor_requested.is_set():
                    try:
                        self._do_monitor(cam, sdk, self.monitor_params)
                    except Exception as exc:
                        self.output_queue.put(("CAPTURE_ERROR", f"Monitor: {exc}"))
                    finally:
                        self.monitor_requested.clear()
                        self.monitor_stop.clear()
                    continue
```

Add the two methods next to `_do_capture`:

```python
    def _do_monitor(self, cam, sdk, params):
        """Continuous grab + online detection until Stop Monitoring.

        Hot path per frame: grab -> np copy -> release -> engine.feed ->
        throttled preview. Event frames are written by the background
        EventWriter; nothing in this loop touches the disk.
        """
        ok = sdk["IMV_OK"]
        before = params.before if params is not None else 30
        after = params.after if params is not None else 30
        eng = monitor.MonitorEngine(before=before, after=after)
        writer = frame_writer.EventWriter(
            lambda d, saved_ok, msg: self.output_queue.put(
                ("MONITOR_SAVED", (d, saved_ok, msg))))
        self.output_queue.put(("STATUS", "MONITORING (armed)"))
        self.output_queue.put(
            "Monitoring started. Fire injections at will; "
            "click Stop Monitoring to finish.\n")
        n_events = 0
        last_preview = 0.0
        try:
            while not (self.monitor_stop.is_set() or self.preview_stop.is_set()):
                frame = sdk["IMV_Frame"]()
                ret = cam.IMV_GetFrame(frame, 1000)
                if ret != ok:
                    continue
                try:
                    info = frame.frameInfo
                    w, h = info.width, info.height
                    flat = np.frombuffer(
                        string_at(frame.pData, w * h), dtype=np.uint8)
                    gray = flat.reshape(h, w).copy()
                finally:
                    cam.IMV_ReleaseFrame(frame)

                event = eng.feed(gray)
                now = time.perf_counter()
                if now - last_preview > 0.04:            # ~25 fps preview
                    last_preview = now
                    self.preview_queue.put(("IMAGE", Image.fromarray(gray)))
                if event is not None:
                    n_events += 1
                    self._dispatch_monitor_event(
                        event, writer, before, after, n_events)
            # Stop pressed mid-jet: close and keep the partial event (it is
            # saved AND processed, per the user's decision).
            tail = eng.flush()
            if tail is not None:
                n_events += 1
                self._dispatch_monitor_event(
                    tail, writer, before, after, n_events)
        finally:
            writer.close()
            self.output_queue.put((
                "MONITOR_STOPPED",
                f"Monitoring stopped: {n_events} injection(s), "
                f"{eng.stats['fed']} frames examined."))

    def _dispatch_monitor_event(self, event, writer, before, after, n_events):
        """Reserve the event's folder, queue the async write, and post the
        make_result-shaped payload the UI holds until MONITOR_SAVED."""
        h, w = event["frames"][0].shape
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        dest_dir = injection_extract.make_dest_dir(
            Path(f"monitor_{stamp}_{w}x{h}"), INJECTION_DIR)
        # Create the folder NOW (cheap, once per event) so the next event's
        # make_dest_dir sees it and picks a unique name even while the
        # writer is still working through its queue.
        dest_dir.mkdir(parents=True, exist_ok=True)
        meta = smart_save.make_meta(event["bounds"], event["window"],
                                    "monitor (online)")
        writer.submit(str(dest_dir), event["names"], event["frames"], meta)
        result = smart_save.make_result(
            event["seq_names"], event["seq_signal"], event["bounds"],
            event["window"], source_dir="monitor", dest_dir=str(dest_dir),
            before=before, after=after, method="monitor (online)")
        note = f" [{event['dropped_note']}]" if event["dropped_note"] else ""
        self.output_queue.put(
            f"Injection #{n_events} detected -> {dest_dir.name} "
            f"({len(event['names'])} frames){note}\n")
        self.output_queue.put(
            ("STATUS", f"MONITORING (armed) - {n_events} injection(s)"))
        self.output_queue.put(("MONITOR_EVENT", result))
```

(`make_dest_dir(source_dir, dest_base)` uses only `source_dir.name` — passing a bare `Path("monitor_...")` is deliberate; verified at `hsc/injection_extract.py:396`.)

- [ ] **Step 5: Wire the mixin into the app** — `hsc/gui/app.py`:

Add the import (alphabetical, after `MeasurementMixin`):

```python
from hsc.gui.monitor import MonitorMixin
```

Add `MonitorMixin` to the bases after `MeasurementMixin`:

```python
class CaptureGui(
    LayoutMixin,
    CaptureMixin,
    CameraWorkerMixin,
    ExtractionMixin,
    MeasurementMixin,
    MonitorMixin,
    VideoMixin,
    CalibrationMixin,
    ReferenceMixin,
    tk.Tk,
):
```

And in `__init__`, after `self._init_capture_state()`:

```python
        self._init_monitor_state()
```

- [ ] **Step 6: Button** — `hsc/gui/layout.py`: after the `self.stop_button = ...` line add

```python
        self.monitor_button = ttk.Button(
            actions, text="Start Monitoring", command=self._toggle_monitor
        )
```

and insert `self.monitor_button` into the `buttons` tuple right after `self.stop_button` (the grid flows automatically, 4 per row).

- [ ] **Step 7: Camera-death + chain-end hooks** —

`hsc/gui/capture.py`, in `_drain_preview_queue`'s `STOPPED` branch, after the stranded-still-request reset loop:

```python
                    # Monitoring cannot continue without the camera; return
                    # the toggle + camera buttons to idle (idempotent).
                    self._reset_monitor_ui()
```

`hsc/gui/video.py`: append to BOTH `_on_video_done` and `_on_video_error` (last line of each):

```python
        # End of the auto chain: start the next queued monitor event, if any.
        self._pump_monitor_chain()
```

(`_pump_monitor_chain` lives on `MonitorMixin`, always present in `CaptureGui`; the video mixin is never used standalone. A failed measure still chains into the video step — `_on_measure_error` calls `_maybe_auto_video_after_measure` — so VIDEO_DONE/VIDEO_ERROR is the single end-of-chain point in every path.)

`tests/test_gui_structure.py`: add to the `expected` set in `test_expected_message_kinds_present`:

```python
        "MONITOR_EVENT", "MONITOR_SAVED", "MONITOR_STOPPED",
```

- [ ] **Step 8: Verify headless**

```bash
uv run python -m py_compile hsc/gui/monitor.py hsc/gui/camera_worker.py hsc/gui/app.py hsc/gui/layout.py hsc/gui/capture.py hsc/gui/video.py hsc/monitor.py hsc/frame_writer.py && echo COMPILE-OK
uv run python -m pytest -q
```

Expected: COMPILE-OK, full suite green (including the new wiring tests and the updated `test_gui_structure.py`). Self-review the diff for: no change to any existing handler, `_do_capture`, or the preview grab path beyond the listed insertions; the monitor loop releases every SDK frame in a `finally`; nothing blocks the grab loop (writer is async; `_dispatch_monitor_event` only mkdirs + queues).

- [ ] **Step 9: Commit**

```bash
git add hsc/gui/monitor.py hsc/gui/camera_worker.py hsc/gui/app.py hsc/gui/layout.py hsc/gui/capture.py hsc/gui/video.py tests/test_monitor_wiring.py tests/test_gui_structure.py
git commit -m "feat: Monitor mode -- continuous multi-injection capture with auto chain"
```

---

### Task 5: Docs + on-rig validation checklist

**Files:** Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: README** — new short section "Monitor mode": what the button does (continuous detection, one `data\injection images\monitor_<stamp>_<WxH>` folder per injection, auto measure+video per event — video last, matching the capture chain; Stop finalizes and processes any in-flight event; camera-owning buttons are disabled while monitoring); the camera-safety note (continuous streaming is the sensor's normal duty cycle — the live preview already streams continuously; no mechanical shutter; just keep the camera ventilated, as sustained max-FPS streaming runs it warm and warmth adds a little image noise); and the validation command `uv run python -m hsc.monitor "data\captures\<run>" --compare`.

- [ ] **Step 2: CLAUDE.md** — module map entries for `hsc/monitor.py` (streaming engine, `MON_END_FRAC` is the one online-specific tunable, replay CLI is the validation tool) and `hsc/frame_writer.py`; extend the `hsc/gui/` bullet with `monitor.py` (Start/Stop Monitoring toggle, `monitor_requested`/`monitor_stop`, results held until `MONITOR_SAVED`, `_monitor_chain` FIFO pumped from the video handlers, `_do_monitor` in `camera_worker.py`); a data-flow line: monitor events land directly under `data\injection images\monitor_<stamp>_<WxH>` with `injection_meta.json`, nothing in `data\captures\`.

- [ ] **Step 3: On-rig checklist** (goes in the final report to the user; the feature ships opt-in — there is no default to flip, but the checklist gates *trusting* it):
  1. Replay `--compare` on several real recorded bursts → all `OK` (tune `MON_END_FRAC` per Task 2 if not).
  2. Start Monitoring, fire ONE injection → folder appears, frame count sane, measure+video complete, status returns to armed.
  3. Fire TWO injections ~10 s apart → two folders, both chained in order, none lost (the second fires while the first is saving/measuring).
  4. Walk a hand through the frame → if it triggers, confirm the junk event is short (runaway cap / quick end) and monitoring re-arms; note the false-trigger behavior in the log.
  5. Stop Monitoring mid-jet → partial event saved AND measured, clean stop message.
  6. 30-minute soak with no injections → RAM flat (Task Manager), preview live, no drift in the status line; optionally check the camera body temperature by touch — warm is normal, untouchably hot is a ventilation problem.
  7. Compare the logged examined-frames rate against the camera's configured FPS → they should match; a persistent shortfall means the feed path is dropping frames (report it, don't ignore it).

- [ ] **Step 4: Final verification + commit**

```bash
uv run python -m pytest -q
FOLDER=$(ls -d "data/injection images"/*/ | head -1) && uv run python run_gui.py --selftest "$FOLDER"
git add README.md CLAUDE.md
git commit -m "docs: monitor mode usage, camera-safety note, on-rig validation checklist"
```

---

## Final acceptance checklist

1. Full suite green (existing 62 + ~14 new tests across engine/replay/writer/wiring).
2. Replay `--compare` prints `OK` on the synthetic burst and on all real bursts available on the dev machine.
3. Reviewer confirms: grab hot path minimal, every SDK frame released, no existing flow touched except the listed insertion points.
4. User completes the 7-point on-rig checklist before relying on monitor mode for real test campaigns.

## Explicitly out of scope

- Hardware/TTL triggering (still the standing rig question — it would demote the software trigger to a cross-check).
- Auto-restart of monitoring after a camera error (the STOPPED reset returns to idle; the operator restarts).
- Commissioning-time raw full-window dumps to `captures\` (add later if trust-building demands it).
- Any change to detection constants or the measurement pipeline.
