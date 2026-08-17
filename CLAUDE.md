# CLAUDE.md

Guidance for AI agents working in this repository. Read this before changing code.

## What this project is

A Windows toolkit for a **needle-free injector** test rig: a high-speed camera records a
high-pressure **water jet**, and the code (1) captures bursts, (2) extracts the short
injection event from thousands of frames, and (3) measures the **spray angle** of the jet.

Pipeline: **capture → find injection → measure angle**.

A second, parallel pipeline measures the **piston speed**: the same camera watches the nozzle
piston travel down the barrel while the dose is expelled (**capture piston → find injection
piston → measure piston**), producing a distance/speed-vs-time record of the stroke.

**The rig is driven by the HTTP/WebSocket service in `hsc/api/` and by the module CLIs.**
The Tkinter desktop app that used to chain these pipelines from buttons was retired on
2026-08-17 (see *Retired: the Tk app* below) — nothing in this repo opens a window today.
The piston pipeline is what the service drives end to end; the spray-angle pipeline, monitor
mode and the calibration/reference dialogs are CLI-only or not yet driven at all, and the
React UI that replaces the window arrives in a later slice.



## Design & Implementation Principles

- Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.

- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.

- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works. Never trade a working product for unfinished complexity.

- Keep components modular and concerns clearly separated.
 
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.

- Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume a library lacks a capability without checking its documentation and types.

- Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.



## Module map

- **`hsc/hardware/`, `hsc/rig/`, `hsc/api/`** — the service that drives the rig; see their
  own entries below. **There is no GUI package**: `hsc/gui/`, `hsc/capture_gui.py`,
  `hsc/calibrate_ui.py`, `hsc/reference_ui.py` and `run_gui.py` were deleted on 2026-08-17.
- **`hsc/capture_image.py`** — IMV SDK access + capture logic (`capture_burst`, `configure_camera`,
  `make_run_output_dir`, `ASPECT_PRESETS`). Standalone CLI too. Loads the SDK from
  `vendor/Development/Samples/Python/IMV/MVSDK` and DLLs from `vendor/Runtime/x64`.
  **Capture ROI** — the rig-measured table, which lived in the deleted `gui/config.py` and now
  survives only here. `320x240`/`320x120` → **1048/1798 fps**, measured on the rig 2026-08-12
  with zero dropped frames. `320x64` (2624 fps) was measured and then **withdrawn**: it crops
  into the barrel (48 usable rows vs 79 at both remaining sizes) and the piston there is grey
  with a collar that detaches mid-stroke, so no single edge rule held across a stroke. To use
  that rate, re-aim the camera so the barrel FILLS the short frame. The rate is bound by
  **row readout, not exposure** — 100 µs, 200 µs and 500 µs all give the identical rate at a
  given height, so keep the exposure up for contrast and shorten the ROI for speed. But cap it
  at the frame period or the ROI drops below its rate: **950 µs at 320x240, 550 µs at
  320x120**. Exceeding the cap costs BOTH speed and contrast — at 320x64 the default 500 µs
  dropped the rate to 1830 fps AND lifted the piston from black (min 4) to grey (min 38),
  leaving the detector nothing to lock onto; two rig runs on 2026-08-13 failed that way.
  The API takes `width`/`height`/`exposure_us` straight from the caller and does **not**
  enforce any of this — these are the numbers a UI should offer. A short ROI is the only way
  to resolve the injection's opening transient (~2.9 ms: barely 3 frames at 1048 fps, ~7.6 at
  2624 — below that the reported peak speed is set by the smoothing window, not by the
  piston). **Cropping does not change mm/px** (that is optics, not sensor rows), so the stored
  calibration stays valid at every ROI; `configure_camera` only programs Width/Height when the
  grab thread starts, so the camera must be stopped before a new ROI takes effect.
- **`hsc/injection_extract.py`** — temporal-motion detection of the injection. `extract_injection`
  (disk) and `build_result` + `detect_bounds_with_presence` (the in-memory path: detect, then write only the window).
  Motion-signal back-ends: `scan_with_cpp` → `compute_motion_signal_raw` → `compute_motion_signal`
  (PIL). Onset from temporal diff; end from a jet-presence signal (downsampled).
- **`hsc/smart_save.py`** — pure planning for the *detect-before-write* capture path (the Tk
  app's "Smart save"; no SDK imports, unit-testable headless). **No live caller today** — the
  rig service writes the full piston burst — but it is the validated shape for a smart spray
  capture, and its CLI still checks decisions against recorded bursts. `plan_window` wraps the
  unchanged `detect_bounds_with_presence` and returns `(bounds, (copy_start, copy_end))` using
  `build_result`'s clamp math (`(None, None)` ⇒ no injection, caller does a full legacy save);
  `make_result` builds the exact `build_result` key set, so a caller can hand its output
  straight to whatever consumes a find-injection result; `make_meta`/`write_meta` emit
  `injection_meta.json`. `replay(source_dir)` +
  CLI `uv run python -m hsc.smart_save "data\captures\<run>" --compare` re-run the decision on
  an existing burst and diff it against the legacy extractor (validation: should say IDENTICAL).
- **`hsc/monitor.py`** — streaming (online) injection detection for Monitor mode. **Kept
  deliberately although nothing starts a session today** (its only driver was the Tk grab
  loop): it is camera-free, tested, has a replay CLI, and encodes rig-earned detection
  thresholds that would be expensive to rediscover. Same for `hsc/frame_writer.py`.
  `MonitorEngine(before, after, ...)` is a pure state machine (`armed → recording → padding →
  armed`) fed one frame at a time via `feed()` (returns a closed event dict or None) with a
  bounded pre-trigger ring buffer; `flush()` closes an in-flight event on Stop. Detection
  watches only the **left `MON_DETECT_FRAC` (2/3) of the columns** (the nozzle at the right
  edge is removed/reinstalled between injections while monitoring — that churn must not
  trigger; saved frames are full width). Trigger =
  temporal count > `MON_TRIGGER` (300); **end = the temporal signal stays quiet
  (≤ max(`MON_END_ABS` 30, `MON_END_FRAC` 0.005 × event peak)) for `MON_END_HOLD` (60)
  frames** — deliberately NO presence-vs-background end rule: online, the pre-trigger
  background goes stale the moment the injection wets/mists the scene, presence then never
  drops and every event runs into the cap (root-caused on-rig 2026-07-10; the offline detector
  escapes only by thresholding off the post-jet trough it can scan ahead to). At close the
  event is validated: peak < `MON_MIN_PEAK` (3000) ⇒ `discarded` set (drips/mist trip the
  300-px trigger but real injections peak 6k–55k; junk ≤760 — measured). Validation tool:
  `uv run python -m hsc.monitor "data\captures\<run>" --compare` replays a recorded burst and
  checks that a kept online event's saved window covers the offline detector's window (`OK`).
- **`hsc/piston_track.py`** — piston edge tracking (camera-free, unit-testable). The piston is a
  **dark body on a bright barrel interior** — the inverse of the jet — so it has its own
  detector, sharing only the line fitting with `measure_angle`. **The hard part is not finding
  an edge, it is always finding the SAME edge**: the silhouette breaks into a rim, a reflective
  sliver, a leading blob and a trailing skirt, and a static seal sits a few px behind the
  resting position. Every row-local rule tried first (first dark run, then longest dark run,
  then window tracking against the previous frame) picked a different fragment in different
  rows or different frames, producing 25 px steps mid-stroke and ±14 px of baseline scatter —
  all root-caused on rig run `piston_2026-08-07-15-55-38` (see the tests named for each).
  What works, in order:
  1. `build_profile` (once per run): temporal max/min over sampled frames → the barrel row band
     (bright rows, `_restrict_to_body` then drops barrel rows the piston never sweeps —
     the barrel is taller than the piston), the dark/bright levels (per-run, not per-frame Otsu,
     whose threshold would follow the piston's changing share of the frame), and
     **`static`**: pixels dark in EVERY frame. Those are subtracted per frame, so the seal,
     holder and border vanish and only the MOVING piston is labelled — the same background-first
     principle `measure_angle` uses for the jet. A pixel the piston never vacates is
     indistinguishable from static, but the left EDGE always sweeps, so it always survives.
  2. `refine_band` (on the STROKE frames only — at rest every row agrees and it learns nothing):
     scores each row by how far its edge sits from the frame's median and keeps the run that
     agrees within `AGREE_TOL`, collapsing the band onto the piston's flat face.
  3. `edge_columns`: largest **connected** dark region (2-D, so fragments separated in one row
     but touching in another resolve into the one object they physically are), leftmost column
     per row, `GAP_CLOSE` horizontal closing first, parabolic gradient vertex for sub-pixel
     (`_parabolic_offsets`, vectorised but asserted identical to
     `measure_angle._parabolic_vertex_offset`), then RANSAC→TLS as `x = k*y + b`.

  `line_distance` is the perpendicular distance between two such lines along the REFERENCE
  line's normal at the band centre row (well-defined when they are not exactly parallel).
  `detect_piston_bounds` derives the stroke window from the **displacement curve itself** — NOT
  from the jet's temporal-motion signal, so mist and turbulence cannot move it — using two
  thresholds: a coarse `MOVE_TRAVEL_FRAC`-of-observed-travel trigger that baseline wander
  cannot fire (a sigma taken from 20 head frames fired 2700 frames early), then a walk back to
  the true onset by **local step** (`ONSET_SPEED_FRAC`), and the mirror of that at the end (the
  coarse plateau fits while the piston still creeps). The walk back must test "is it moving
  HERE?", never "is it far from where it started?": over thousands of frames the barrel drifts
  further than any displacement floor, so that test never sees rest and the walk runs to
  `MAX_ONSET_WALK` — on run 2026-08-12-14-07-22 it stopped 194 frames early and padded the
  copied window with 185 ms of resting frames (displacement had already reached 1.03 px there,
  vs a 0.6 px floor). The local step separates the states by an order of magnitude: 0.02 px
  median at rest, 0.30 px worst case, against 1.73 px mid-stroke. `implausible_steps` flags frames whose step exceeds
  `MAX_STEP_PX` — a detector identity switch, not motion. Those frames are **reported only**
  (the CSV's `stable` column + a warning), never suppressed: `peak_speed_mm_s` is the plain
  maximum of the `speed_mm_s` column, so the plotted curve and the summary are always the same
  numbers. An earlier version excluded them *and* their Savitzky–Golay neighbours, which made
  the summary quote 108.5 mm/s while the curve plainly showed 131.1 (rig run
  2026-08-07-17-41-15); the operator reads the curve, so the two must never disagree.
  `scan_positions` is the **Find piston V2** path (`extract_piston_event(fast=True)`, the
  `fast` job param): same stroke window, ~30x faster. Three changes, all safe because every reported
  number is re-measured by `measure_piston` on the copied window with the full fit — (1) a
  **coarse pass at every `SCAN_STRIDE` (8) frame brackets the stroke and only that bracket
  (plus the head, which sets the rest baseline) is read densely**; (2) frames are read across
  `SCAN_WORKERS` (8) threads; (3) the position is the median of the per-row edge columns
  instead of a RANSAC→TLS fit. Validated against a full scan on all 49 rig bursts: identical
  windows, 20% of the frames read, 271.8 s → 32.0 s.
  `_motion_bracket` keys off the **step** between coarse samples, never the displacement: the
  piston stays where it stopped, so a displacement test reads "moved" from the onset to the end
  of the recording and brackets half the burst.
  **Do not reach for C++ here**: profiling a 4194-frame burst showed the 80 s was ~74 s of
  *serial cold disk seeks* (22.06 ms/file one at a time vs 1.11 ms/file across 8 threads) plus
  2.7 ms/frame of sklearn RANSAC — only ~2.2 s was work a faster language could touch at all,
  and skipping frames beat that outright (0.54 s vs the ~1.1 s a perfect rewrite could reach)
  without a second copy of the detector to keep in step. 16 threads was slower than 8.
  `extract_piston_event` copies the padded window to
  `data\injection images\` with `piston_meta.json` (a superset of `injection_meta.json`, so the
  spray tools still read it).
  CLI: `uv run python -m hsc.piston_track "data\captures\<run>"`.
- **`hsc/measure_piston.py`** — per-frame green edge line + distance/speed/curves.
  `measure_folder` writes annotated frames (native capture size, `PISTON_LINE_SS` supersample
  then area-downscale, same thin-line trick as `measure_angle`), `piston_speed.csv`
  (`frame,time_ms,x_px,distance_px,distance_mm,speed_mm_s,speed_m_s,k,n_points,rms_px,
  coverage,at_border,stable` + a summary block) and `distance_time.png` / `speed_time.png` into
  `data\measure\<run>\`. Distance is measured from the **stroke-start frame**'s line; mm come
  from `calibrate_scale.load_calibration()` (warns when the stored `image_size` differs from the
  frames — the mm then assume the same magnification; **no calibration ⇒ px only**, never a
  silently wrong mm). `resolve_timebase` is the honest-time-axis rule: frame index is NOT time
  (the camera free-runs and can drop frames), so it prefers the per-frame timestamps recorded by
  Capture Piston — but only after **inferring their tick unit** (us/ns/ms) by agreeing with the
  burst's measured FPS within `TIMEBASE_TOL`; timestamps that agree with nothing fall back to
  the FPS, and with neither it raises rather than invent a plausible-looking curve.
  **Never take the time base from the camera's `AcquisitionFrameRate`**: the rig never enables
  `AcquisitionFrameRateEnable` (`frame_rate=None`), so the camera free-runs at its maximum and
  that feature reports a stale stored value — it printed 525 while the bursts actually ran at
  ~1048 fps (measured 2026-08-07). Believing it would halve every reported speed. Speed is the
  Savitzky–Golay derivative (central difference when timestamps are unevenly spaced).
  CLI: `uv run python -m hsc.measure_piston "<folder>" [--fps N] [--mm-per-px X]`.
- **`hsc/summary.py`** — descriptive statistics ACROSS measured runs. It re-reads the summary block each run already wrote into its
  `*_speed.csv`, so a run folder needs no extra metadata to take part and old archives can be
  summarised retroactively. Reports n / mean / std / **cv_percent** / min / median / max for
  stroke, peak piston speed, duration, and peak jet speed + pressure; `cv_percent` is the one
  that answers "is this injector repeatable", which is usually why a batch was run. Writes
  `summary_<stamp>.csv` to the **measure root**, beside the runs it describes: a per-run table,
  then the statistics block, then any folders that were skipped **with the reason** — quietly
  averaging fewer runs than the operator selected would be the worst outcome. Runs measured
  before the jet columns existed still contribute their stroke and speed (per-metric `n`).
  CLI: `uv run python -m hsc.summary "data\measure\<run>" ... [--dest DIR]`.
- **`hsc/piston_plot.py`** — tiny OpenCV XY line plotter (nice 1/2/5 ticks, grid, rotated y
  label, NaN gaps break the curve). Deliberately not matplotlib: it would add tens of MB for
  two plots. That mattered to the frozen one-folder build, which does not exist in this slice —
  keep the rationale in view for when packaging returns rather than adding matplotlib now and
  discovering the cost at build time.
- **`hsc/frame_writer.py`** — `EventWriter`: background thread that writes a monitor event's
  BMP frames with cv2 (no SDK) + `injection_meta.json`, then reports
  `(dest_dir, ok, msg)` through a callback (→ `MONITOR_SAVED`); errors are reported, never
  raised into the grab loop.
- **`native/injection_scan.cpp` / `vendor/bin/injection_scan.exe`** — C++/OpenMP scanner that
  returns the temporal motion signal as int32 stdout. Built statically via
  `native/build_injection_scan.bat` (MinGW g++; outputs to `vendor\bin\`). Optional:
  Python falls back if absent.
- **`hsc/measure_angle.py`** — spray-angle pipeline (see below). `measure_folder` (service/CLI),
  `measure_single` (one image), `measure_frame` (one frame), plus modular steps.
- **`hsc/make_video.py`** — builds a **slow-motion** playback video from an injection-images folder
  (`make_video`; CLI + the piston job's last phase). Writes `slowmo.mp4` (mp4v, fallback MJPG
  `.avi`) as a single file *directly inside the selected folder* at a low playback fps
  (`VIDEO_FPS`, default 15 → slow motion). Pure OpenCV, no SDK/camera needed.
- **`hsc/calibrate_scale.py`** — spatial calibration (mm per pixel) from **two
  reference edges a known distance apart** via an **ROI workflow** (whole-frame auto-detect is
  unreliable against the nozzle/reflection clutter, so the ROIs are supplied). The Tk dialog
  that drew them (`calibrate_ui.CalibrationDialog`, deleted 2026-08-17, in git history for the
  React port) grabbed a still to `data\measure\block\` and had the user box each edge and click
  *Detect Edge*; today the ROIs come from the CLI or from `auto_rois`.
  `detect_edge_in_roi` scans each ROI (orientation from ROI aspect), finds the sub-pixel edge per
  scan line, fits a line by RANSAC→TLS (reusing `measure_angle` helpers), and `_line_gap` takes
  the perpendicular pixel distance; `mm_per_px = ref_mm / gap_px`. **Block polarity is
  auto-detected** (default `mode="auto"`): the current **5 mm block images as a bright bar on a
  dark background**, so its two reference edges are the bright↔dark **steps** at the block boundary
  (`mode="step"`, the polarity-agnostic gradient peak); the older chamfered block images as a
  bright block with **dark edge-lines** (`mode="outer"`: `_scanline_outer_edge` walks from the dark
  min to the steepest-gradient flank facing *away from the other ROI*). `_auto_fit_mode` /
  `_roi_is_dark_line` inspect the ROIs and use `outer` only when BOTH look like dark lines, else
  `step`. `mode` "dark"/"bright"/"step" force the feature extremum. Draws both green lines + ROI boxes
  + gap connector + mm/px onto `*_scale.bmp` and writes `calibration.json` (to `settings\` at the repo root via `settings_path`).
  CLI for scripting/tests: `uv run python -m hsc.calibrate_scale still.bmp --ref-mm 5 --roi1 x0 y0 x1 y1
  --roi2 x0 y0 x1 y1` (`--mode` defaults to `auto`). **Auto-calibration** skips the ROI step
  entirely:
  `auto_rois` finds the two block edges in the left `region_frac` (default 1/3, avoiding the
  right-side clutter) by **per-scanline two-edge voting** — `_two_edges_bright` (longest bright run
  per scan line → its two step boundaries, for the bright block) tried first, then `_two_lines`
  (two-trough voting, for a dark-line block), in both orientations; the candidate with the most
  supporting scan lines wins and its `fit_mode` is returned. Robust to a tilted or locally-faint
  edge that a collapsed 1-D profile would wash out; refuses if two well-separated edges aren't
  present in most scan lines. Builds an ROI around each and runs the fit in the detected mode
  (`auto_calibrate_image`). **`measure_block_size`** is the inverse: it
  auto-detects a block's two edges and reports its size in **mm** using the stored calibration
  **without** overwriting `calibration.json` (writes a `*_measured.bmp`). `load_calibration()` is
  the read API. NB: `auto_calibrate_image` always *saves* a new calibration (assuming the entered
  distance); `measure_block_size` only *reads* it — calibrate on the known reference, then
  measure others.
  `save_calibration` / `save_reference` back up any existing JSON to `<name>.bak` and write
  atomically (temp file + `os.replace`) so a crash mid-save can't corrupt the rig's calibration.
- **`hsc/reference_lines.py`** — nozzle **reference lines**: the **tip edge**
  (red) and the **centerline** (blue, through the tip midpoint, perpendicular, across the frame =
  spray axis). The retired Tk flow captured a nozzle still (to `data\reference line\`, no jet in
  view) and opened `reference_ui.ReferenceDialog`, where the user **dragged along the nozzle tip
  edge to draw the thin red line directly** — auto-detect is unreliable on the reflective nozzle,
  so a human placed it, and the React port must keep that. `build_reference` builds the blue
  centerline from that line. `save_check_image`
  writes a **native-resolution** (1-px) overlay. A **mm-sized rectangle** reference is also added
  (`attach_rectangle`, needs the scale calibration): a thin red box centered on the centerline,
  with near/far vertical edges `RECT_NEAR_MM`/`RECT_FAR_MM` (1.0 / 6.51 mm) downstream of the red
  line and height `RECT_HEIGHT_MM` (0.775 mm) — a jet target band. The reference (lines + rect) is
  stored in `reference_lines.json` (`settings\` at the repo root) and overlaid on every measured frame by
  `measure_folder` when the frame size matches. (`detect_tip_in_roi` /
  `set_reference_from_image/_folder` = auto-detect helpers, kept for CLI.) `NOZZLE_SIDE` = right.
- **`hsc/hardware/`** — the seam between rig code and the vendor SDK.
  `device.py` is the protocol; `imv.py` is the real adapter and the ONLY file
  excluded from coverage — a test parses it and fails if it grows any logic;
  `fake.py` replays a saved burst and is what every test above the seam runs
  against, including faults (dropped frames, wrong ROI, a fault status) that used
  to be reproducible only on the rig. `grab()` returns a **`Grab`** — the SDK's raw
  status, the OK status to compare it with, and an unevaluated frame builder that is
  `None` unless the grab succeeded — because *what a non-OK status means* is a
  decision, and decisions may not live in the coverage-excluded adapter.
  `hsc/rig/worker.py` makes it and records which status ended the burst; an
  earlier version decided in `imv.py` through a dict lookup the AST guard could
  not see, and flattened every fault into "the burst just ended".
- **`hsc/rig/`** — the service: one camera worker, piston pipeline jobs with
  phases and cancellation, the single-controller lease, the event bus and the
  SQLite store. Imports no web framework (asserted by `tests/test_layering.py`)
  so the whole pipeline is testable without a server. Three rules here were each
  paid for once: `store.add_run` **merges** with `COALESCE` (the importer re-scans
  at every start and knows none of the capture-side columns — a blind upsert
  erased them on the first restart after every run); `measure_dir` is the UNIQUE
  key and **both** writers `resolve()` it (else `--data-root .` and the default
  absolute root duplicate every run); and `JobManager.close` **refuses to close
  the device** while a job is still alive, returning their ids instead — a
  cancelled burst still has ~18 000 BMPs to write, so outliving the join is
  routine, and closing under a live SDK call is what the next process cannot
  recover from.
- **`hsc/api/`** — FastAPI over `hsc/rig/`: REST, `/ws/events` (JSON) and
  `/ws/preview` (binary JPEG), and the `RuntimeError` -> error-code mapping
  that lets the UI show the lighting numbers next to a failed capture.
  Run with `uv run python -m hsc.api --host <tailscale-ip>` (`__main__.py`:
  `--host`, `--port`, `--data-root`, `--spa <built frontend dir>`, `--cors
  <origin>` repeatable; `build()` is the wiring, split out so it is covered).
  There is no application-level authentication — the tailnet is the security
  boundary.
- **`hsc/app_paths.py`** — `resource_root()` (bundled read-only files: SDK, `Runtime` DLLs,
  `bin/injection_scan.exe`) returns `vendor/`: `<root>/vendor` from source,
  `<sys._MEIPASS>/vendor` when frozen (PyInstaller). `data_root()` (user output:
  captures/injection images/measure, calibration/reference JSON) returns `<root>/data` from
  source (created on demand), the .exe folder when frozen. Used by `capture_image`
  (SDK/Runtime), `injection_extract` (scan exe), `hsc/rig` and `hsc/api`.

## Retired: the Tk app (2026-08-17)

`hsc/gui/` (15 modules), `hsc/capture_gui.py`, `hsc/calibrate_ui.py`, `hsc/reference_ui.py`
and `run_gui.py` were deleted once the rig service replaced their backend. **Git history is
the reference for all of it** — the dialogs in particular are the starting point for the
React port. What went with them, so nobody hunts for a caller that no longer exists:

- **Live preview, Monitor mode, and the capture→measure→video chaining.** `/ws/preview`
  CONSUMES bus events of kind `preview`, but **nothing publishes them** — both references
  to that kind in `hsc/api/` are consumers (`ws_preview.py` sends them, `ws_events.py`
  filters them out), so the socket is a working sink waiting for a continuous grab loop to
  feed it. Do not go looking for the publisher; it has to be written. `hsc/monitor.py` and
  `hsc/frame_writer.py` are likewise kept and tested but have no driver. Chaining now
  lives in `hsc/rig/jobs.py`, for the piston pipeline only.
- **Interactive calibration and reference drawing.** One stale pointer is knowingly left
  behind: `hsc/calibrate_scale.py`'s module docstring still sends the reader to
  `calibrate_ui.py` for interactive use. It is an analysis module, validated against real
  rig data from 4 U to 40 U, and this branch modified none of them — the wrong comment is
  cheaper than the first such edit. Fix it in a commit that touches nothing else.
  The non-interactive paths survive:
  `uv run python -m hsc.calibrate_scale <still> --ref-mm 5 --roi1 ... --roi2 ...`,
  `auto_calibrate_image`, `measure_block_size`, and `set_reference_from_image/_folder`.
- **`--selftest`** and the frozen one-folder Windows build. `packaging/HighSpeedCamera.spec`
  + `packaging/build_exe.bat` were removed with it (their entry point was `run_gui.py`), and
  PyInstaller left the dev dependencies. A frozen build returns when there is a web build to
  bundle; `docs/DISTRIBUTION.md` covers running from source until then, and `hsc/app_paths.py`
  keeps its `sys._MEIPASS` branch ready. When that build is written, the spec must again
  bundle the `vendor/` tree (`Runtime/x64`, the `Development/.../MVSDK` wrapper,
  `bin/injection_scan.exe`) **preserving the relative paths inside `vendor/`** — the vendor
  `IMVApi.py` loads `MVSDKmd.dll` by the relative path
  `../../../../../Runtime/x64/MVSDKmd.dll`, so that layout must be kept.
- **Fixed capture policies** the GUI hardwired and the service now owns: `defer_save=True`,
  `no_save=False`, `timestamp_dir=True`, and injection padding 30/30
  (`PAD_BEFORE`/`PAD_AFTER`, now in `hsc/rig/jobs.py`).

The **piston video is built from the `measure` folder, not the injection folder**, so it shows
the fitted green line tracking the piston — every wrong edge in this pipeline was caught by
watching that, not by reading numbers. Keep it that way. `make_video.list_frames` keeps only
the largest same-size group of images, because a measure folder also holds the report plots
and `VideoWriter` is fixed at one frame size.

## Data flow & folders

All user output lives under `data\` (gitignored), via `data_root()`:

- `data\captures\<timestamp>_<aspect>\frame_000001.bmp …` — raw burst (one folder per run;
  timestamp format `yyyy-mm-dd-hh-mm-ss`, e.g. `2026-07-13-09-28-10_320x240`).
- `data\injection images\<run>\…` — extracted injection window (`copy_start … copy_end`); the
  video step also writes `slowmo.mp4` here. A *detect-before-write* capture (`smart_save`)
  would create the run folder **directly here** with `injection_meta.json` and leave
  `data\captures\` empty for that run, as would a **Monitor mode** event
  (`monitor_<stamp>_<WxH>\`); neither has a live driver today, so in practice the full burst
  lands in `data\captures\` first as below.
- `data\captures\piston_<timestamp>_<aspect>\…` — a **piston capture** burst (every frame
  kept, plus `piston_capture.json` with the per-frame camera timestamps). Its stroke window
  lands in `data\injection images\` like any other, with `piston_meta.json` alongside.
- `data\measure\<run>\…` + `angles.csv` — annotated angle images and report. A piston run
  writes `piston_speed.csv` + `distance_time.png` + `speed_time.png` here instead.
- `data\calibration.json` / `data\reference_lines.json` — the saved scale calibration and
  nozzle reference.
- `data\rig.db` — the service's SQLite run index (`hsc/rig/store.py`), created by
  `hsc.api.__main__.build()` under `--data-root` and filled from `data\measure\` on
  startup by `hsc.rig.importer`. Mostly an index of folders that already exist — but
  **not entirely**: `source_dir`, `injection_dir`, `exposure_us`, `measured_count`,
  `truncated` and `dropped` are written only by the pipeline and cannot be recovered from
  a measure folder, so deleting the file loses them for every past run. That is also why
  `add_run` merges instead of overwriting (see `hsc/rig/store.py`) — the startup rescan
  used to erase exactly those columns. There is **no schema migration**: the columns are
  created by `CREATE TABLE IF NOT EXISTS`, so a `rig.db` made by an older build of this
  branch must be deleted rather than upgraded.

**Run label.** The optional run label (the capture job's `label` param) is appended to
every run folder — `<timestamp>_<aspect>_<label>`, `piston_…_<label>`, `monitor_…_<label>` — and
rides from there into the injection-images and measure folders for free, because `make_dest_dir`
names them after the source. `capture_image.safe_label` strips the characters Windows forbids,
folds whitespace to `-`, and caps at `LABEL_MAX` (48) so the full path stays inside the 260-char
limit; an empty/unusable label leaves names exactly as they were. **Reports are named after
their own folder** so a file copied out of it still identifies its run:
`<run>_speed.csv` / `<run>_distance_time.png` / `<run>_speed_time.png`
(`measure_piston.output_path` + the `*_SUFFIX` constants), `<run>_angles.csv`
(`measure_angle`), `<run>_slowmo.mp4` (`make_video`). Annotated frames keep
`frame_000123.bmp` — they have to stay 1:1 with the source frames.

`make_dest_dir` adds a `_2`, `_3`, … counter suffix if a destination folder already exists,
so re-runs (and monitor events closing within the same second) don't overwrite. The `data\captures\` contents change between sessions (the user
captures/cleans); don't assume a specific run folder exists — glob for it.

## hsc/measure_angle.py pipeline (canonical)

`Gaussian blur → Otsu → largest connected component → column-wise gradient edge extraction
(subpixel) → Savitzky–Golay → ROI → RANSAC outlier rejection → Total Least Squares fit →
angle → visualization/report`, using OpenCV + NumPy + SciPy +
scikit-learn. Key, hard-won design decisions (do not regress these without reason):

- **Edge-detection V2 (opt-in, benchmark-gated; edge/policy defaults stay legacy).** Three
  flags, flipped together by the `edge_v2()` context manager (`V2_FLAGS` is the set, and a
  caller opts in by wrapping its measure run in the context manager):
  `EDGE_MODEL="erf"` adds a per-side blurred-step fit `I(y)=base+amp·Φ((y−μ)/σ)` per column
  as a THIRD candidate locus in the straightness contest (each side gets its own σ, so a
  skirted lower edge stops dragging its line; per-column confidence → `edge_conf_*`);
  `BG_MODE="pre-onset"` builds the background only from the jet-free padding frames at the
  folder start (count from `injection_meta.json`, written by `build_result`; silent fallback
  to the window median — the result key `bg_mode` reports what was actually used).
  **`BG_MODE="pre-onset"` is the DEFAULT** (not V2-gated): a steady jet dominates the
  whole-window median, gets subtracted away, fails `MIN_PEAK`, and `measure_folder`'s
  jet-frame counter then skips the real steady phase — the measured frames land ~100 frames
  late in the decay (root-caused on run `20260710_100958`). Meta-less folders fall back to
  the window median and behave exactly as before;
  `ANGLE_POLICY="trusted"` reports the trusted edge alone when exactly one edge is
  Low-confidence (per-edge `edge_quality` scores; `q_up,q_lo,policy` in `angles.csv`).
  `POOLED_FIT` (always on) additionally reports `pooled_angle`: one RANSAC→TLS fit per edge
  over ALL measured frames' raw edge samples. `"legacy"`/`"window"`/`"max"` reproduce the old
  behavior exactly (verified by tests). Gate results live in `benchmark/baseline.csv` vs
  `benchmark/results/candidate.csv`.

- **Background subtraction first** (per-pixel temporal median) so Otsu/segmentation see only
  the moving jet — the rig has a bright static nozzle/holder that would otherwise dominate the
  largest component.
- **Edge = steepest intensity gradient on the RAW image within the jet band**, not the binary
  mask boundary. The Otsu mask tilts with brightness and the visible white includes a static
  residual stream; the raw-within-band gradient tracks the visible edge and handles the jet's
  asymmetric skirt/reflection (one side falls off slower).
- **Band extended outward on the raw image** (`EDGE_BAND_FRAC`, `EDGE_BAND_MAX` in
  `extract_edges`). A very *steady* jet is present in most injection frames, so the temporal-median
  background contains the jet core; subtraction then removes it and the Otsu mask stops **short of
  the visible edge** on the side where the static background is bright — clipping the search band so
  the true gradient ramp is excluded and the edge lands 2–3 px inside the white. Before searching,
  each column's band is walked OUTWARD along the raw column while it stays above
  `bg + EDGE_BAND_FRAC·(core−bg)` (capped at `EDGE_BAND_MAX`), recovering the clipped edge. Only
  fires when the mask boundary still sits on bright pixels; a correct boundary has background just
  outside it so the walk stops immediately (no effect on well-segmented frames).
- **Two candidate loci per edge, auto-selected** (`EDGE_VISIBLE_FRAC`, `_pick_edge_locus`): the
  gradient peak marks the ~50% ramp point, ~0.5–1 px inside what the eye reads as the edge —
  glaring on thin (~5 px) jets. A second locus walks outward to the per-column
  `bg + 0.25·(core−bg)` crossing (subpixel). Per edge, the locus whose ROI points form the
  straighter line (robust sigma, visible preferred within `EDGE_PICK_TOL`) wins: thin/sharp
  edges get the visible crossing, skirt/reflection edges keep the noise-immune gradient peak.
  `measure_block` uses the gradient-only path (its calibration is unchanged).
- **Subpixel edges**: each gradient peak is refined by parabolic interpolation of the 3 gradient
  samples straddling it (`_parabolic_vertex_offset`), so edge rows are continuous, not integer.
- **RANSAC → TLS** per edge: RANSAC rejects droplet/splash/breakup outliers, then the inliers are
  fit by **Total Least Squares** (PCA major axis, `tls_fit` / `_tls_direction`) which minimizes
  orthogonal distance — correct when both edge coordinates are noisy, unlike OLS. (For
  near-horizontal jet edges with exact column-x, TLS ≈ OLS; the gain is largest for steeper edges
  e.g. the angle block.)
- **Reported angle = max deviation from the spray axis** (when a nozzle reference is set):
  `line_angle_deg` gives the acute angle between the blue centerline and each green edge
  (`angle_upper`, `angle_lower`); `measure_folder` reports the **larger** of the two (the worst
  edge). Computed in pass 2 where the reference is loaded; it overrides the `angle` and flows into
  the image, `angles.csv`, mean/std/confidence. With no reference set it falls back to the
  edge-to-edge spray angle `|atan(k_up) − atan(k_lo)|` (`spray_angle`). The green edge lines are
  also clipped to the reference rectangle's x-window (`_clip_lines_to_x`) for the jet-vs-rectangle
  check; the fit/angle is unaffected by the clip. When a rect is set, each frame also gets a
  **jet-in-rectangle verdict** (`jet_in_rect`: both edge lines inside the rect bbox over its
  x-window ⇒ `OK`, else `NG`) — the `in_rect`
  column of `angles.csv`, and `frame_in_rect` in the result dict (empty without a reference).
- Frames are selected by **jet-frame index** (`start..end`, default 10–20), counted from the
  first frame containing a jet (padding skipped) — measures the steady jet, skips the burst.
  **`auto_pick=True`** (ignoring `start`/`end`) instead measures
  the FIRST run of `AUTO_PICK_COUNT` (10) file-consecutive frames whose jet is stable —
  span spread ≤ `AUTO_STABLE_TOL` of the window median AND angle spread ≤
  `AUTO_STABLE_ANGLE_TOL` (the angle check is essential: a fast jet reaches full span on its
  first frame, so during the burst only the angle is still settling). No qualifying window ⇒
  the steadiest run seen is used and `auto_pick_fallback` is set
  (`measure_folder(..., auto_pick=True)`, `find_stable_window`).
- **Line-quality standard + confidence** (`QUALITY_*`, `frame_quality`, `confidence_level`):
  each frame scores 0–100 = min(fit, coverage, span) where fit = robust RMS of raw subpixel
  edges vs the fitted line, coverage = ROI columns with an edge, span = jet length vs run max
  (catches injection decay, the main source of angle scatter). ≥75 High / ≥50 Medium / else Low,
  drawn on the image and written to `angles.csv`. Run confidence = min(median frame score,
  angle-std score). `trusted_mean` excludes Low frames. Measurement itself is unchanged by all
  of this — quality is computed on top.
- Saved measure frames are **native capture size** (320×240) by default — `MEASURE_RENDER_SCALE`
  (=1) controls this; set it to `SUPERSAMPLE` (3) for 960×720 supersampled output with more zoom
  detail. Native size makes the reference-line overlay land at the same pixels as the reference
  check image. Lines are drawn supersampled (`MEASURE_LINE_SS`=2) then area-downscaled to the
  output size, so they end up ~½ px thin/anti-aliased. Output lines are **green**, drawn from a gap near
  the nozzle (`APEX_GAP`) out to the image edge on the tip side. Nozzle assumed on the **right**
  (`NOZZLE_SIDE = +1`).

## Conventions / gotchas

- **Windows-only paths and APIs**: the camera SDK, and the backslash paths throughout. (The
  last `os.startfile` call went with the GUI's "Open Last Folder" button — `git grep startfile`
  now returns nothing, so nothing in `hsc/` shells out to the shell any more.) Python 3.13,
  managed by **uv**: `uv sync` once creates `.venv/` from `pyproject.toml` + `uv.lock` (dev
  group = pytest, pytest-cov, pytest-asyncio, httpx — **no PyInstaller**, it was dropped with
  the Tk app); prefix commands with `uv run`.
- Run module CLIs with `uv run python -m hsc.<module>` from the repo root; the package is never
  pip-installed (`tool.uv.package = false` — it runs in place).
- Capture needs the IMV SDK + camera; **measurement does not** (pure cv2/scipy/sklearn on saved
  images), so you can iterate on `hsc/injection_extract.py` / `hsc/measure_angle.py` without hardware.
- BMP frames here are uncompressed 8-bit, often read fast via `injection_extract._bmp_info`
  (header parse) + `np.fromfile` instead of PIL/cv2 decode. **Row order matters**: the IMV SDK
  saves top-down BMPs (biHeight < 0) but `cv2.imwrite` (frame_writer/EventWriter, i.e. every
  Monitor-mode folder) saves bottom-up (biHeight > 0). `_bmp_info` returns a `bottom_up` flag
  and all raw readers (`load_gray`, `raw_downsample_getter`, `_read_raw_pixels`,
  `make_video._read_bgr`) flip accordingly — regression 2026-07-10: monitor folders were
  measured upside down and the jet landed ~30 px off the reference line.
- All three motion back-ends must produce the **same** signal — verify equality if you touch them.
- Don't break the service contracts: `measure_folder(source, dest_base, start, end, progress)`,
  `piston_track.extract_piston_event(...)`, `measure_piston.measure_folder(...)` and
  `make_video.make_video(...)` are called by `hsc/rig/jobs.py`;
  `injection_extract.detect_bounds_with_presence(...)` / `build_result(...)` are the
  in-memory detection entry points.

## How to verify changes

- Tests: `uv run python -m pytest` (426: import smoke, monitor engine/replay, frame writer,
  BMP row order, smart save, run-folder/report naming, synthetic wedge, edge-detection V2
  (erf/pre-onset/quality/pooled/toggle), piston edge tracking / speed (synthetic strokes with
  exact ground truth), calibration load, vendor layout, data root, plus the service layers:
  hardware seam / fake camera, rig store, importer, lease, events, worker, jobs, the API
  routes and both WebSockets, and the layering guard). No camera and no server are needed —
  nothing binds a port. One skip is expected (symlinks need privileges on Windows); a
  second appears under `--cov`, because the erf-edge budget test measures wall clock and
  refuses to judge a traced run.
  Compile check:
  `uv run python -m py_compile hsc/*.py hsc/hardware/*.py hsc/rig/*.py hsc/api/*.py benchmark/*.py`.
- **Coverage gate** for the service layers (run it before merging anything under
  `hsc/hardware/`, `hsc/rig/`, `hsc/api/`):
  ```powershell
  uv run python -m pytest --cov=hsc.hardware --cov=hsc.rig --cov=hsc.api --cov-report=term-missing --cov-fail-under=100
  ```
  100% is required. The single documented omission is `hsc/hardware/imv.py`
  (`[tool.coverage.run] omit` in `pyproject.toml`), which cannot run without a camera —
  and that exclusion is only honest because `tests/hardware/test_imv_has_no_logic.py`
  parses the file and fails if it grows any branching or computation. Fix an uncovered
  line by adding the test, never by widening the omit list. `tests/test_layering.py`
  is the other half: it parses every `hsc/rig/` **and `hsc/hardware/`** module's imports
  (11 today) and fails on
  fastapi/starlette/uvicorn/`hsc.api` — the hardware seam was in neither rule until
  2026-08-17, being exempt from the analysis sweep as a service package — and sweeps the
  whole analysis layer — everything
  under `hsc/` except the three service packages, `EXPECTED_ANALYSIS`, 16 modules today,
  recursively (proved by `test_the_sweep_is_recursive` over a temp tree, since every
  analysis module happens to sit at the top level now) — for imports of
  `hsc.rig` / `hsc.api`. Matching is by **prefix**: the real
  form of the violation is `from hsc.api.app import create_app`, which an equality test
  would miss, so `violations()` treats a forbidden name as matched by the package and
  anything below it — pinned by the guard's own probe tests.
  `test_erf_mode_meets_perf_budget` skips itself under `--cov`
  (tracing inflates wall clock — a timing assertion must not make the gate flaky).
- Edge-detection accuracy: `uv run python -m benchmark.run_benchmark <tag>` writes
  `benchmark/results/<tag>.csv` (synthetic wedges with exact ground truth); compare against
  the committed `benchmark/baseline.csv` (legacy scores). Flip flags via
  `measure_angle.edge_v2()` or per-flag module attributes for what-if runs.
- Measurement: run `uv run python -m hsc.measure_angle` on an existing `data\injection images\<run>`
  folder; render a
  saved frame (native 320×240 by default; raise `MEASURE_RENDER_SCALE` for a zoomable 960×720)
  and inspect that the green lines sit on the white jet edges.
  Reading an annotated `.bmp` requires converting to PNG first to view it.
- The live camera can't run in a headless/agent environment — verify logic and saved-image
  output against `hsc/hardware/fake.py`, and ask the user to confirm the flow on the rig.

## Do / don't

- **Do** keep changes minimal and preserve the iteratively-tuned defaults (`EDGE_*`, `RANSAC_*`,
  `NOZZLE_SIDE`, `MEASURE_START/END`, padding). They reflect real user feedback on this rig.
- **Don't** commit, push, or add/upgrade dependencies unless asked. (Everything needed is in
  `pyproject.toml`/`uv.lock`; `uv sync` recreates the environment.)
- **Don't** delete the user's `data\captures\`, `data\injection images\`, or `data\measure\`
  data, or the hand-drawn reference images, without explicit instruction.
