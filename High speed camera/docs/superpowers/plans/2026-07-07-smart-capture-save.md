# Smart Capture Save (detect-before-write) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make find-injection effectively instant and cut per-capture disk writes ~15× by reordering the capture pipeline: compute the motion signal and detect the injection window **in RAM before saving**, then write **only the window frames** directly into `data\injection images\<run>` — instead of today's write-all-4,000-BMPs-then-copy-260-back-out.

**Architecture:** The grab loop (the 1000 fps hot path) is untouched — frames are cloned to RAM exactly as today. The change is entirely in the post-burst phase of `_capture_frames` in `hsc/capture_gui.py`: a RAM-only signal pass, the *existing, unchanged* `detect_bounds_with_presence`, then a selective save. All window/result math lives in a new pure module `hsc/smart_save.py` so it is unit-testable without a camera, and is proven equal to `build_result`'s window by test. The feature is a GUI checkbox ("Smart save"), **default OFF** until validated on the rig; unchecked behavior is bit-identical to today. When smart save is off, no detection code changes at all.

**Tech Stack:** Python 3.13 via uv, NumPy (already locked), pytest. No new dependencies. No camera needed for any test.

## Global Constraints

- Branch: `git checkout -b smart-save` from `main`. Conventional commits, commit per task. Run everything from the repo root `D:\01_Data\code\spray-angle-test\High speed camera` (quote it — spaces). Tests: `uv run python -m pytest ...`; the full existing suite must stay green after every task.
- **Do not touch the grab loop** (`hsc/capture_gui.py` `_capture_frames` while-loop, lines ~471–493) or any SDK call pattern (`IMV_CloneFrame`/`IMV_ReleaseFrame`/`save_frame` usage stays exactly as-is; only *which* frames get `save_frame`d changes, in the post-burst phase).
- **Detection algorithms are unchanged**: `detect_bounds_with_presence`, `detect_injection_bounds`, all thresholds (`DIFF_THRESH`, `min_peak`, `gap`, presence constants) keep their current values and code. This plan changes *when* detection runs and *what gets written*, never *how* detection decides.
- **Window math must be provably identical** to `injection_extract.build_result`: `copy_start = max(0, start - before)`, `copy_end = min(n - 1, end + after)` — an equivalence test enforces it.
- **Never lose frames:** if smart mode finds no injection, ALL frames are saved to `data\captures\<run>` exactly as today and the legacy chain runs. Smart mode only ever *skips writes* of frames that legacy would have discarded after copying.
- GUI contracts preserved: `CAPTURE_DONE`/`EXTRACT_DONE` queue message kinds keep working; `_on_extract_done(result)` receives a dict with the exact key set `build_result` returns today (listed in Task 1); `injection_extract` public functions unchanged (nothing in it is modified by this plan).
- `injection_meta.json` written by the smart path uses the same schema as the edge-detection-v2 plan's Task 3 (`pre_frames`, `onset_index`, `copy_start`, `copy_end`, `method`) so the two features compose; if that plan has landed first, both paths simply produce the same file.
- The GUI cannot run headless: Task 3's GUI wiring is verified by `py_compile`, the pure-module tests, and careful review — plus the Task 4 on-rig checklist for the user. Say so in reports; do not fake GUI verification.
- Out of scope (do NOT implement): hardware/TTL triggering (a rig question for the user), a bounded ring buffer (RAM use is unchanged from today's defer-save), retiring the C++ scanner, coarse-to-fine disk scanning, jet-region masking.

---

### Task 1: `hsc/smart_save.py` — pure window planning + result/meta builders

**Files:**
- Create: `hsc/smart_save.py`
- Test: `tests/test_smart_save.py`

**Interfaces:**
- Produces (consumed by Task 3's worker):
  - `plan_window(signal, frame_getter, n, before, after) -> (bounds, window) | (None, None)` — bounds `(start, end, peak)` from the unchanged `detect_bounds_with_presence`; window `(copy_start, copy_end)` with `build_result`'s exact clamp math.
  - `make_result(frame_names, signal, bounds, window, source_dir, dest_dir, before, after, method) -> dict` — same keys/values as `injection_extract.build_result`'s return: `source_dir, dest_dir, method, total_frames, peak_index, peak_frame, peak_value, injection_start_frame, injection_end_frame, injection_count, copy_start_frame, copy_end_frame, selected_count, before, after, copied`.
  - `make_meta(bounds, window, method) -> dict` — the `injection_meta.json` payload.

- [ ] **Step 1: Write the failing tests** (`tests/test_smart_save.py`)

```python
"""smart_save: window planning must match build_result's math exactly."""
import numpy as np
import pytest

from hsc import injection_extract, smart_save


def _synthetic_burst(n=60, onset=20, end=45, w=160, h=120):
    """In-RAM burst: static scene, a ~400 px jet appears at `onset` and
    vanishes at `end`. Returns (full_res_frames, signal, small_frames)."""
    ds = injection_extract.DOWNSAMPLE
    scene = np.full((h, w), 15, np.int16)
    jet = scene.copy()
    jet[55:65, 20:60] = 220                     # 40x10 = 400 px > min_peak 300
    frames = [jet if onset <= i < end else scene for i in range(n)]
    signal = np.zeros(n)
    for i in range(1, n):
        signal[i] = float(np.count_nonzero(
            np.abs(frames[i] - frames[i - 1]) > injection_extract.DIFF_THRESH))
    small = [f[::ds, ::ds].astype(np.int16) for f in frames]
    return frames, signal, small


def test_plan_window_finds_the_event_and_clamps():
    _, signal, small = _synthetic_burst()
    bounds, window = smart_save.plan_window(
        signal, lambda i: small[i], len(small), before=30, after=30)
    assert bounds is not None
    start, end, peak = bounds
    assert 18 <= start <= 21          # onset at 20 (+-gap tolerance)
    assert window[0] == max(0, start - 30)          # clamped at 0 here
    assert window[1] == min(len(small) - 1, end + 30)


def test_plan_window_none_when_no_injection():
    n = 40
    signal = np.zeros(n)
    small = [np.zeros((30, 40), np.int16)] * n
    bounds, window = smart_save.plan_window(signal, lambda i: small[i], n, 30, 30)
    assert bounds is None and window is None


def test_window_math_equals_build_result(tmp_path):
    """The one invariant that matters: smart_save selects the SAME files that
    build_result would copy, and make_result mirrors its dict exactly."""
    _, signal, small = _synthetic_burst()
    n = len(small)
    names = [f"frame_{i + 1:06d}.bmp" for i in range(n)]
    fake_files = [tmp_path / nm for nm in names]
    bounds, window = smart_save.plan_window(
        signal, lambda i: small[i], n, before=5, after=7)
    start, end, peak = bounds
    ref = injection_extract.build_result(
        fake_files, signal, "m", start, end, peak,
        source_dir=tmp_path / "run", dest_base=tmp_path / "inj",
        before=5, after=7, copy=False)
    assert window == (max(0, start - 5), min(n - 1, end + 7))
    assert ref["copy_start_frame"] == names[window[0]]
    assert ref["copy_end_frame"] == names[window[1]]
    ours = smart_save.make_result(
        names, signal, bounds, window,
        source_dir=str(tmp_path / "run"), dest_dir=ref["dest_dir"],
        before=5, after=7, method="m")
    # ref was built with copy=False so its "copied" is False; smart save's
    # result always reports copied=True (it wrote the frames itself).
    assert ours == {**ref, "copied": True}


def test_make_meta_matches_edge_v2_schema():
    meta = smart_save.make_meta((20, 45, 21), (15, 52), "in-memory (smart save)")
    assert meta == {"pre_frames": 5, "onset_index": 20, "copy_start": 15,
                    "copy_end": 52, "method": "in-memory (smart save)"}
```

- [ ] **Step 2: Run — must fail** (`uv run python -m pytest tests/test_smart_save.py -v` → ModuleNotFoundError)

- [ ] **Step 3: Implement `hsc/smart_save.py`**

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Pure planning logic for smart capture save (detect-before-write).

The capture worker holds every burst frame in RAM (defer-save). Instead of
writing all of them to ``captures\\`` and then copying the injection window
back out, smart save detects the window FIRST (same detection code as always)
and writes only the window frames, directly into the injection-images run
folder. This module is the camera-free part: window planning, the
build_result-compatible metadata dict, and the injection_meta.json payload.
Kept free of SDK/Tk imports so it is unit-testable headless.
"""

import numpy as np

from hsc import injection_extract


def plan_window(signal, frame_getter, n, before, after):
    """Detect the injection and return ``(bounds, window)``.

    ``bounds`` is ``(start, end, peak)`` from the unchanged
    ``detect_bounds_with_presence``; ``window`` is ``(copy_start, copy_end)``
    using exactly ``build_result``'s clamp math. Returns ``(None, None)``
    when no injection is present (caller falls back to a full legacy save).
    """
    bounds = injection_extract.detect_bounds_with_presence(
        np.asarray(signal, dtype=np.float64), frame_getter, n)
    if bounds is None:
        return None, None
    start, end, _ = bounds
    window = (max(0, start - int(before)), min(int(n) - 1, end + int(after)))
    return bounds, window


def make_result(frame_names, signal, bounds, window, source_dir, dest_dir,
                before, after, method):
    """Metadata dict with the exact key set ``build_result`` returns, so the
    GUI's ``_on_extract_done`` consumes it unchanged."""
    signal = np.asarray(signal, dtype=np.float64)
    start, end, peak = bounds
    copy_start, copy_end = window
    return {
        "source_dir": str(source_dir),
        "dest_dir": str(dest_dir),
        "method": method,
        "total_frames": len(frame_names),
        "peak_index": peak,
        "peak_frame": frame_names[peak],
        "peak_value": int(signal[peak]),
        "injection_start_frame": frame_names[start],
        "injection_end_frame": frame_names[end],
        "injection_count": end - start + 1,
        "copy_start_frame": frame_names[copy_start],
        "copy_end_frame": frame_names[copy_end],
        "selected_count": copy_end - copy_start + 1,
        "before": before,
        "after": after,
        "copied": True,
    }


def make_meta(bounds, window, method):
    """injection_meta.json payload (same schema as injection_extract's)."""
    start, _end, _peak = bounds
    copy_start, copy_end = window
    return {
        "pre_frames": int(start - copy_start),
        "onset_index": int(start),
        "copy_start": int(copy_start),
        "copy_end": int(copy_end),
        "method": str(method),
    }
```

CAREFUL on one detail in the equivalence test: `build_result` returns `peak_frame` etc. as `files[i].name` (a `Path.name` string) — `make_result` receives plain name strings, so the dicts compare equal only if the test's `fake_files` are `Path`s whose `.name` equals `names[i]` (they are, by construction). If the assertion fails on `dest_dir`, pass `ref["dest_dir"]` through as shown — `make_dest_dir` naming is exercised in Task 3, not here.

- [ ] **Step 4: Run tests** — 4 PASS. Full suite: `uv run python -m pytest -q` → all green.

- [ ] **Step 5: Commit**

```bash
git add hsc/smart_save.py tests/test_smart_save.py
git commit -m "feat: pure window-planning module for smart capture save"
```

---

### Task 2: Replay CLI — validate smart planning against any existing burst on disk

Lets the user (and CI-less us) prove on *real rig data* that smart save would have kept exactly the frames the legacy pipeline kept.

**Files:**
- Modify: `hsc/smart_save.py` (add `replay()` + `__main__`)
- Test: `tests/test_smart_save_replay.py`

**Interfaces:**
- Produces: `smart_save.replay(source_dir, before=30, after=30) -> dict` with keys `bounds, window, names` (selected frame names) — and CLI `uv run python -m hsc.smart_save "data\captures\<run>"` printing the window and, with `--compare`, the diff vs `extract_injection`'s selection (must print `IDENTICAL`).

- [ ] **Step 1: Failing test** (`tests/test_smart_save_replay.py`)

```python
"""Replay on a disk burst must select the same window extract_injection copies."""
import cv2
import numpy as np

from hsc import injection_extract, smart_save


def _write_burst(folder, n=60, onset=20, end=45, w=160, h=120):
    folder.mkdir(parents=True)
    scene = np.full((h, w), 15, np.uint8)
    jet = scene.copy()
    jet[55:65, 20:60] = 220
    for i in range(n):
        cv2.imwrite(str(folder / f"frame_{i + 1:06d}.bmp"),
                    jet if onset <= i < end else scene)


def test_replay_matches_extract_injection(tmp_path):
    src = tmp_path / "burst"
    _write_burst(src)
    rep = smart_save.replay(src, before=5, after=7)
    assert rep["bounds"] is not None
    legacy = injection_extract.extract_injection(
        src, dest_base=tmp_path / "inj", before=5, after=7, copy=True)
    copied = sorted(p.name for p in
                    (tmp_path / "inj").rglob("frame_*.bmp"))
    assert rep["names"] == copied
```

- [ ] **Step 2: Run — fail** (no `replay`).

- [ ] **Step 3: Implement** — append to `hsc/smart_save.py`:

```python
def replay(source_dir, before=30, after=30):
    """Re-run the smart-save decision on an existing burst folder on disk.

    Uses the same signal back-ends and downsampled presence frames as the
    offline extractor, so the result shows exactly what smart save WOULD have
    kept for this burst. Returns {"bounds", "window", "names"}.
    """
    files = injection_extract.list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")
    signal, _method = injection_extract.compute_motion_signal_best(files)
    getter = injection_extract.raw_downsample_getter(files)
    if getter is None:                       # non-BMP burst: decode via PIL
        from PIL import Image
        ds = injection_extract.DOWNSAMPLE
        def getter(i):
            img = np.asarray(Image.open(files[i]).convert("L"), dtype=np.int16)
            return img[::ds, ::ds]
    bounds, window = plan_window(signal, getter, len(files), before, after)
    names = ([] if window is None
             else [f.name for f in files[window[0] : window[1] + 1]])
    return {"bounds": bounds, "window": window, "names": names}


def _main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Replay the smart-save decision on an existing burst.")
    parser.add_argument("source", help="a data\\captures\\<run> folder")
    parser.add_argument("--before", type=int, default=30)
    parser.add_argument("--after", type=int, default=30)
    parser.add_argument("--compare", action="store_true",
                        help="also run the legacy detector and diff the windows")
    args = parser.parse_args()

    rep = replay(args.source, args.before, args.after)
    if rep["bounds"] is None:
        print("no injection detected (legacy full save would apply)")
        return
    start, end, peak = rep["bounds"]
    print(f"bounds: start={start} end={end} peak={peak}")
    print(f"window: frames {rep['window'][0]}..{rep['window'][1]} "
          f"({len(rep['names'])} files kept of "
          f"{len(injection_extract.list_frames(args.source))})")
    if args.compare:
        legacy = injection_extract.extract_injection(
            args.source, before=args.before, after=args.after, copy=False)
        same = (legacy["copy_start_frame"] == rep["names"][0]
                and legacy["copy_end_frame"] == rep["names"][-1])
        print("IDENTICAL to legacy extraction" if same else
              f"DIFFERS: legacy {legacy['copy_start_frame']}.."
              f"{legacy['copy_end_frame']}")


if __name__ == "__main__":
    _main()
```

VERIFY before relying on `--compare`: `extract_injection` must accept `copy=False` and return without creating folders (read its body — it has a `copy` parameter; if its dest handling differs, adapt the compare to use `detect` results the way `replay` does rather than changing `injection_extract`).

- [ ] **Step 4: Run** — new test PASS; full suite green. Then run the replay against a REAL burst if one exists on this machine: `ls "data/captures"` — for each run folder (if any), `uv run python -m hsc.smart_save "data/captures/<run>" --compare` → expect `IDENTICAL`. Record the output in the task report (skip gracefully if `data/captures` is empty — the user cleans it).

- [ ] **Step 5: Commit**

```bash
git add hsc/smart_save.py tests/test_smart_save_replay.py
git commit -m "feat: smart-save replay CLI to validate against recorded bursts"
```

---

### Task 3: GUI integration — "Smart save" checkbox + detect-before-write in the capture worker

**Files:**
- Modify: `hsc/capture_gui.py` (checkbox, params field, post-burst phase of `_capture_frames`, `CAPTURE_DONE` handler)

**Interfaces:**
- Consumes: `smart_save.plan_window/make_result/make_meta` (Task 1), `injection_extract.make_dest_dir`, existing `INJECTION_DIR` constant in `capture_gui.py`.
- Produces: `CAPTURE_DONE` payload may carry a new optional key `"extract_result"` (a `build_result`-shaped dict). No other message contract changes.

- [ ] **Step 1: Add the checkbox and params field**

Next to the existing Defer save checkbox (`hsc/capture_gui.py` ~line 97 and ~line 153):

```python
        self.smart_save_var = tk.BooleanVar(value=False)
```

```python
        ttk.Checkbutton(checks, text="Smart save",
                        variable=self.smart_save_var).pack(side=tk.LEFT)
```

Find the capture-params construction (`grep -n "defer_save=" hsc/capture_gui.py`, ~line 305) and its params class definition (grep for the class/namedtuple holding `defer_save`); add a `smart_save` field defaulting to `False` and pass `smart_save=self.smart_save_var.get(),` alongside `defer_save`.

- [ ] **Step 2: Reorder the post-burst phase of `_capture_frames`**

Replace the current block that starts at `saved_paths = []` (after the grab loop's `fps = ...` line, ~line 498) through the `CAPTURE_DONE` put (~line 580) with the following. It is the SAME code re-arranged into pass A (RAM signal), detect, pass B (save), with the smart branch added — diff your result against the original to confirm the legacy path is line-for-line preserved:

```python
            saved_paths = []
            motion_signal = None
            small_frames = []
            extract_result = None
            bounds = None
            ds = injection_extract.DOWNSAMPLE
            smart = bool(getattr(params, "smart_save", False)
                         and params.defer_save and not params.no_save)
            if cloned_frames:
                # Pass A (RAM only): motion signal + downsampled copies.
                # No disk I/O here -- this is what lets smart mode decide the
                # window BEFORE anything is written.
                motion_signal = []
                prev_pixels = None
                for clone_frame in cloned_frames:
                    info = clone_frame.frameInfo
                    w, h = info.width, info.height
                    n_pixels = w * h
                    flat = np.frombuffer(
                        string_at(clone_frame.pData, n_pixels), dtype=np.uint8
                    )
                    pixels = flat.astype(np.int16)
                    if prev_pixels is not None and prev_pixels.shape == pixels.shape:
                        motion_signal.append(
                            float(
                                np.count_nonzero(
                                    np.abs(pixels - prev_pixels)
                                    > injection_extract.DIFF_THRESH
                                )
                            )
                        )
                    else:
                        motion_signal.append(0.0)
                    prev_pixels = pixels
                    small_frames.append(flat.reshape(h, w)[::ds, ::ds].copy())

                # Detect BEFORE saving (same detection code as always; the
                # window math lives in smart_save.plan_window, proven equal
                # to build_result's by test).
                window = None
                try:
                    bounds, window = smart_save.plan_window(
                        motion_signal,
                        lambda i: small_frames[i].astype(np.int16),
                        len(small_frames), params.before, params.after,
                    )
                except Exception as exc:
                    bounds, window = None, None
                    self.output_queue.put(f"[Detect warning] {exc}\n")

                self.output_queue.put(
                    f"Captured {captured} frames in {elapsed:.3f}s, "
                    f"capture FPS: {fps:.1f}\n"
                )

                save_start = time.perf_counter()
                if smart and bounds is not None:
                    # Smart save: write ONLY the window, directly into the
                    # injection-images run folder. Frame names keep their
                    # original burst indices, matching what the legacy
                    # save-then-copy pipeline produces.
                    dest_dir = injection_extract.make_dest_dir(
                        output_dir, INJECTION_DIR)
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    names = [
                        capture_image.make_frame_path(
                            dest_dir, params.prefix, i + 1, suffix).name
                        for i in range(len(cloned_frames))
                    ]
                    for i in range(window[0], window[1] + 1):
                        capture_image.save_frame(
                            cam, cloned_frames[i], dest_dir / names[i], sdk)
                        saved += 1
                    smart_save.write_meta(dest_dir, bounds, window,
                                          "in-memory (smart save)")
                    extract_result = smart_save.make_result(
                        names, motion_signal, bounds, window,
                        source_dir=str(output_dir), dest_dir=str(dest_dir),
                        before=params.before, after=params.after,
                        method="in-memory (smart save)")
                    save_elapsed = time.perf_counter() - save_start
                    self.output_queue.put(
                        f"Smart save: kept {saved} of {captured} frames "
                        f"-> {dest_dir} in {save_elapsed:.3f}s\n"
                    )
                    try:                     # captures run dir stays empty
                        output_dir.rmdir()
                    except OSError:
                        pass
                else:
                    if smart:
                        self.output_queue.put(
                            "Smart save: no injection detected -- "
                            "saving the full burst as usual.\n"
                        )
                    for frame_no, clone_frame in enumerate(cloned_frames, start=1):
                        output_path = capture_image.make_frame_path(
                            output_dir, params.prefix, frame_no, suffix
                        )
                        capture_image.save_frame(cam, clone_frame, output_path, sdk)
                        saved += 1
                        saved_paths.append(str(output_path))
                    save_elapsed = time.perf_counter() - save_start
                    self.output_queue.put(
                        f"Saved {saved} cloned frames to {output_dir} "
                        f"in {save_elapsed:.3f}s\n"
                    )
            else:
                verb = "Captured" if params.no_save else "Saved"
                where = "" if params.no_save else f" to {output_dir}"
                self.output_queue.put(f"{verb} {captured} frames{where}\n")
                self.output_queue.put(
                    f"Elapsed: {elapsed:.3f}s, effective FPS: {fps:.1f}\n"
                )

            self.output_queue.put(
                (
                    "CAPTURE_DONE",
                    {
                        "dir": str(output_dir),
                        "files": saved_paths,
                        "signal": motion_signal,
                        "bounds": bounds,
                        "before": params.before,
                        "after": params.after,
                        "extract_result": extract_result,
                    },
                )
            )
```

Add `from hsc import smart_save` to the imports, and add this tiny helper to `hsc/smart_save.py` (with `import json` and `from pathlib import Path` at its top):

```python
def write_meta(dest_dir, bounds, window, method):
    """Write injection_meta.json (best-effort -- metadata, never a failure)."""
    try:
        (Path(dest_dir) / "injection_meta.json").write_text(
            json.dumps(make_meta(bounds, window, method), indent=2),
            encoding="utf-8")
    except OSError:
        pass
```

Notes the implementer must check while applying: (1) the original computed the signal INSIDE the save loop — confirm nothing else consumed intermediate state from that loop (grep `prev_pixels`, `small_frames` in the file); (2) `output_dir` was `mkdir`'d earlier in `_capture_frames` — the smart path leaves it empty and removes it via the guarded `rmdir()`; the fallback path still uses it; (3) `save_frame` is per-clone-frame with `cam`/`sdk` — unchanged call shape; (4) the `CAPTURE_DONE` payload's `"bounds"` stays populated in BOTH modes so the legacy handler branches keep working.

- [ ] **Step 3: Short-circuit the chain in the `CAPTURE_DONE` handler**

In `_drain_output_queue` (~line 1176), change the auto-chain block to check for the ready-made result first:

```python
                    if not (self.capture_params and self.capture_params.no_save):
                        self.auto_measure_pending = True
                        if info.get("extract_result") is not None:
                            # Smart save already wrote the injection window;
                            # skip straight to the video+measure chain.
                            self._on_extract_done(info["extract_result"])
                        elif info.get("bounds") is not None and info.get("signal"):
                            self._auto_copy_injection(info)
                        elif info.get("signal"):
                            self._auto_extract_from_signal(
                                info["files"], info["signal"]
                            )
                        else:
                            self._find_injection(info["dir"])
```

(`_on_extract_done` runs on the UI thread here — same thread this handler runs on — and consumes exactly the `build_result` key set, which `make_result` reproduces; it sets `last_injection_dir` and chains video→measure via `auto_measure_pending`.)

- [ ] **Step 4: Verify headless**

```bash
uv run python -m py_compile hsc/capture_gui.py hsc/smart_save.py && echo COMPILE-OK
uv run python -m pytest -q
```

Expected: COMPILE-OK; full suite green. Then self-review the diff specifically for: legacy path line-for-line identical when the checkbox is off; `saved`/log message semantics; no SDK call added/removed in the grab loop.

- [ ] **Step 5: Commit**

```bash
git add hsc/capture_gui.py hsc/smart_save.py
git commit -m "feat: Smart save checkbox -- detect injection before writing, save only the window"
```

---

### Task 4: Docs + on-rig validation checklist

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: README** — in the GUI quick-start / buttons area, add: a "Smart save" checkbox description (default off): *detects the injection in RAM before saving and writes only the `before..after` window directly to `data\injection images\<run>` (plus `injection_meta.json`); if no injection is detected the full burst is saved to `data\captures\<run>` as usual. Validate with `uv run python -m hsc.smart_save "data\captures\<run>" --compare` on your own recorded bursts before enabling.*

- [ ] **Step 2: CLAUDE.md** — module map: add a `hsc/smart_save.py` bullet (pure planning module + replay CLI, consumed by `capture_gui`'s smart path); in the `capture_gui.py` bullet note the smart-save branch (detect-before-write, `extract_result` short-circuits the chain); in "Data flow & folders" note that with Smart save enabled `captures\` receives nothing on success and the run folder appears directly under `data\injection images\`.

- [ ] **Step 3: On-rig validation checklist** (paste into the task report / final message for the user — this plan does NOT flip the default; the checkbox stays opt-in):
  1. Replay: run `uv run python -m hsc.smart_save "data\captures\<run>" --compare` on several real bursts → all `IDENTICAL`.
  2. Rig, checkbox OFF: one capture → behavior unchanged.
  3. Rig, checkbox ON: fire an injection → confirm the run folder appears directly under `data\injection images\`, frame count ≈ before+injection+after, `injection_meta.json` present, slow-mo video + measurement chain complete, capture FPS unchanged (grab loop untouched — compare the logged FPS line), and the post-capture wait is visibly shorter.
  4. Rig, checkbox ON, no injection fired: confirm the full burst lands in `data\captures\` with the "no injection detected" log line and the legacy chain messages.
  Only after all four pass should a future commit change the checkbox default to on.

- [ ] **Step 4: Final verification + commit**

```bash
uv run python -m pytest -q
FOLDER=$(ls -d "data/injection images"/*/ | head -1) && uv run python run_gui.py --selftest "$FOLDER"
git add README.md CLAUDE.md
git commit -m "docs: smart capture save usage and validation checklist"
```

---

## Final acceptance checklist

1. Full suite green (existing tests + 5 new).
2. Replay `--compare` reports `IDENTICAL` on the synthetic test and on any real bursts present.
3. Checkbox OFF ⇒ `git diff` of runtime behavior is provably nil (legacy code path preserved line-for-line; reviewer confirms).
4. User completes the four-point on-rig checklist before the default ever flips.

## Explicitly out of scope (future proposals, separate plans)

- **Hardware/TTL trigger** — one question for the user first: does the injector controller expose any electrical fire signal? If yes, that beats all of this.
- Bounded ring buffer for longer captures (RAM use today already holds the full burst; unchanged).
- Retiring `injection_scan.exe` (still useful for the "Find Injection" button on old folders).
- Coarse-to-fine disk scanning; jet-region masking of the motion signal.
