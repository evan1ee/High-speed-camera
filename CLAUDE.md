# CLAUDE.md

Guidance for AI agents working in this repository. Read this before changing code.

## What this project is

A Windows toolkit for a **needle-free injector** test rig: a high-speed camera records a
high-pressure **water jet**, and the code (1) captures bursts, (2) extracts the short
injection event from thousands of frames, and (3) measures the **spray angle** of the jet.

Pipeline: **capture → find injection → measure angle**, chained automatically from the GUI's
Capture button.

## Module map

- **`hsc/gui/`** — Tkinter GUI package, the entry point (`uv run python run_gui.py`;
  `hsc/capture_gui.py` is a thin compatibility shim re-exporting `CaptureGui`/`main`).
  `CaptureGui` (in `gui/app.py`) is assembled from one mixin per feature area:
  `layout.py` (widgets), `capture.py` (preview/Capture UI side + the still-request
  registry), `camera_worker.py` (the persistent camera thread: live preview AND burst
  capture on the *same already-open camera*, so Capture is instant), `extraction.py`
  (Find Injection), `measurement.py` (Measure + Measure Angle Block), `video.py`
  (Make Video), `calibration.py` (Calibrate Scale / Auto Calibrate / Measure Block),
  `reference.py` (Set Reference), `config.py` (shared folders + `log_to_file`),
  `selftest.py` (headless `--selftest`). After a capture it chains:
  `CAPTURE_DONE → auto find-injection (in-memory) → auto make slow-motion video → auto measure`.
  A **"Smart save"** checkbox (default OFF; variable + `smart_save` param in `capture.py`,
  widget in `layout.py`) routes `camera_worker._do_capture` through a *detect-before-write*
  branch: pass A computes the motion signal in RAM, `smart_save.plan_window` detects the
  window, then it writes ONLY the `before..after` frames directly into
  `data\injection images\<run>` (+ `injection_meta.json`, guarded rmdir of the empty
  captures dir) and puts a ready `extract_result` in the CAPTURE_DONE payload — `capture.py`
  `_on_capture_done` dispatches that straight to `_on_extract_done`, **short-circuiting** the
  find-injection step (video → measure chain unchanged). No injection detected / checkbox off
  ⇒ the full burst is saved to `data\captures\<run>` exactly as before.
  Threads talk to the UI via
  `output_queue` / `preview_queue` drained by `after()` callbacks; each mixin declares a
  `QUEUE_HANDLERS` dict (message kind → handler method) merged by
  `app._collect_queue_handlers` — the recipe for adding a new feature module is in the
  `gui/app.py` docstring. `_append_log` mirrors
  every message (timestamped) to `data_root()/app.log` (the frozen build is windowed, so
  that file is the only persistent record); `report_callback_exception` also logs uncaught
  Tk callback tracebacks there. Buttons: Stop Preview,
  Capture, Stop, Find Injection, Measure, Measure Angle Block, Make Video, Calibrate Scale,
  Auto Calibrate, Measure Block, Set Reference, Open Last Folder.
- **`hsc/capture_image.py`** — IMV SDK access + capture logic (`capture_burst`, `configure_camera`,
  `make_run_output_dir`, `ASPECT_PRESETS`). Standalone CLI too. Loads the SDK from
  `vendor/Development/Samples/Python/IMV/MVSDK` and DLLs from `vendor/Runtime/x64`.
- **`hsc/injection_extract.py`** — temporal-motion detection of the injection. `extract_injection`
  (disk) and `build_result` + `detect_bounds_with_presence` (used by the GUI's in-memory path).
  Motion-signal back-ends: `scan_with_cpp` → `compute_motion_signal_raw` → `compute_motion_signal`
  (PIL). Onset from temporal diff; end from a jet-presence signal (downsampled).
- **`hsc/smart_save.py`** — pure planning for the GUI's "Smart save" detect-before-write path
  (no SDK/Tk imports, unit-testable headless). `plan_window` wraps the unchanged
  `detect_bounds_with_presence` and returns `(bounds, (copy_start, copy_end))` using
  `build_result`'s clamp math (`(None, None)` ⇒ no injection, caller does a full legacy save);
  `make_result` builds the exact `build_result` key set so `_on_extract_done` consumes it
  unchanged; `make_meta`/`write_meta` emit `injection_meta.json`. `replay(source_dir)` +
  CLI `uv run python -m hsc.smart_save "data\captures\<run>" --compare` re-run the decision on
  an existing burst and diff it against the legacy extractor (validation: should say IDENTICAL).
- **`native/injection_scan.cpp` / `vendor/bin/injection_scan.exe`** — C++/OpenMP scanner that
  returns the temporal motion signal as int32 stdout. Built statically via
  `native/build_injection_scan.bat` (MinGW g++; outputs to `vendor\bin\`). Optional:
  Python falls back if absent.
- **`hsc/measure_angle.py`** — spray-angle pipeline (see below). `measure_folder` (GUI/CLI),
  `measure_single` (one image), `measure_frame` (one frame), plus modular steps.
- **`hsc/make_video.py`** — builds a **slow-motion** playback video from an injection-images folder
  (`make_video`; GUI "Make Video" button + CLI). Writes `slowmo.mp4` (mp4v, fallback MJPG
  `.avi`) as a single file *directly inside the selected folder* at a low playback fps
  (`VIDEO_FPS`, default 15 → slow motion). Pure OpenCV, no SDK/camera needed.
- **`hsc/calibrate_scale.py` / `hsc/calibrate_ui.py`** — spatial calibration (mm per pixel) from **two
  reference edges a known distance apart** via an **ROI workflow** (whole-frame auto-detect is
  unreliable against the nozzle/reflection clutter, so the user boxes each edge). GUI "Calibrate
  Scale" grabs a still to `data\measure\block\` (uses the "Cal. distance (mm)" field) and opens
  `calibrate_ui.CalibrationDialog`: the user drags an ROI around each edge, clicks *Detect Edge*.
  `detect_edge_in_roi` scans each ROI (orientation from ROI aspect), finds the sub-pixel edge per
  scan line, fits a line by RANSAC→TLS (reusing `measure_angle` helpers), and `_line_gap` takes
  the perpendicular pixel distance; `mm_per_px = ref_mm / gap_px`. Default `mode="outer"`: a
  chamfered block edge images as a **dark line** (chamfer reflects light away), so the true edge
  is the **outer boundary** of that line — `_scanline_outer_edge` walks from the dark min to the
  steepest-gradient flank facing *away from the other ROI* (`calibrate_from_rois` assigns the
  outward sign from the ROI geometry). `mode` "dark"/"bright"/"step" use the feature extremum. Draws both green lines + ROI boxes
  + gap connector + mm/px onto `*_scale.bmp` and writes `calibration.json` (via `data_root()`).
  CLI for scripting/tests: `uv run python -m hsc.calibrate_scale still.bmp --ref-mm 10 --roi1 x0 y0 x1 y1
  --roi2 x0 y0 x1 y1`. **"Auto Calibrate"** button skips the dialog: `auto_rois` finds the two
  dark lines in the left `region_frac` (default 1/3, avoiding the right-side clutter) by
  **per-column two-trough voting** (`_two_lines`; robust to a tilted or locally-faint edge that a
  collapsed 1-D profile would wash out) and refuses if two well-separated edges aren't present in
  most scan lines. Builds an ROI around each and runs the same outer-edge pipeline
  (`auto_calibrate_image`). **"Measure Block"** button (`measure_block_size`) is the inverse: it
  auto-detects a block's two edges and reports its size in **mm** using the stored calibration
  **without** overwriting `calibration.json` (writes a `*_measured.bmp`). `load_calibration()` is
  the read API. NB: Auto Calibrate always *saves* a new calibration (assuming the entered
  distance); Measure Block only *reads* it — calibrate on the known reference, then measure others.
  `save_calibration` / `save_reference` back up any existing JSON to `<name>.bak` and write
  atomically (temp file + `os.replace`) so a crash mid-save can't corrupt the rig's calibration.
- **`hsc/reference_lines.py` / `hsc/reference_ui.py`** — nozzle **reference lines**: the **tip edge**
  (red) and the **centerline** (blue, through the tip midpoint, perpendicular, across the frame =
  spray axis). GUI "Set Reference" **captures a nozzle still** (to `data\measure\reference\`, no jet in
  view) and opens `reference_ui.ReferenceDialog`: the user **drags along the nozzle tip edge to
  draw the thin red line directly** (auto-detect is unreliable on the reflective nozzle, so the
  user places it) and the blue centerline is built live by `build_reference`. `save_check_image`
  writes a **native-resolution** (1-px) overlay. A **mm-sized rectangle** reference is also added
  (`attach_rectangle`, needs the scale calibration): a thin red box centered on the centerline,
  with near/far vertical edges `RECT_NEAR_MM`/`RECT_FAR_MM` (1.0 / 6.51 mm) downstream of the red
  line and height `RECT_HEIGHT_MM` (0.775 mm) — a jet target band. The reference (lines + rect) is
  stored in `reference_lines.json` (`data_root()`) and overlaid on every measured frame by
  `measure_folder` when the frame size matches. (`detect_tip_in_roi` /
  `set_reference_from_image/_folder` = auto-detect helpers, kept for CLI.) `NOZZLE_SIDE` = right.
- **`hsc/app_paths.py`** — `resource_root()` (bundled read-only files: SDK, `Runtime` DLLs,
  `bin/injection_scan.exe`) returns `vendor/`: `<root>/vendor` from source,
  `<sys._MEIPASS>/vendor` when frozen (PyInstaller). `data_root()` (user output:
  captures/injection images/measure, calibration/reference JSON) returns `<root>/data` from
  source (created on demand), the .exe folder when frozen. Used by `capture_image`
  (SDK/Runtime), `injection_extract` (scan exe), `hsc/gui`.

## Packaging (Windows .exe)

`packaging/HighSpeedCamera.spec` + `packaging/build_exe.bat` build a one-folder app via
PyInstaller into `dist\HighSpeedCamera\` (see `docs/DISTRIBUTION.md`); run
`packaging\build_exe.bat` from anywhere (it cds itself). The spec bundles the `vendor/` tree
(`Runtime/x64`, the `Development/.../MVSDK` wrapper, `bin/injection_scan.exe`) **preserving the
relative paths inside `vendor/`** — the vendor `IMVApi.py` loads `MVSDKmd.dll` by the relative
path `../../../../../Runtime/x64/MVSDKmd.dll`, so that layout must be kept (in the built app it
lands under `dist\HighSpeedCamera\_internal\vendor\...`). `uv run python run_gui.py --selftest
"<injection folder>"` runs measure+video headless (writes `selftest.log`) to verify a build
without a camera. `build/` and `dist/` are git-ignored.

## Data flow & folders

All user output lives under `data\` (gitignored), via `data_root()`:

- `data\captures\<timestamp>_<aspect>\frame_000001.bmp …` — raw burst (one folder per run).
- `data\injection images\<run>\…` — extracted injection window (`copy_start … copy_end`); the
  "Make Video" button also writes `slowmo.mp4` here. With **Smart save** enabled and an
  injection detected, the run folder is created **directly here** (with `injection_meta.json`)
  and `data\captures\` receives nothing for that run; with Smart save off, or when no injection
  is detected, the full burst still lands in `data\captures\` first as below.
- `data\measure\<run>\…` + `angles.csv` — annotated angle images and report.
- `data\calibration.json` / `data\reference_lines.json` — the saved scale calibration and
  nozzle reference.

`make_dest_dir` adds an `_HHMMSS` suffix if a destination folder already exists, so re-runs
don't overwrite. The `data\captures\` contents change between sessions (the user
captures/cleans); don't assume a specific run folder exists — glob for it.

## hsc/measure_angle.py pipeline (canonical)

`Gaussian blur → Otsu → largest connected component → column-wise gradient edge extraction
(subpixel) → Savitzky–Golay → ROI → RANSAC outlier rejection → Total Least Squares fit →
angle → visualization/report`, using OpenCV + NumPy + SciPy +
scikit-learn. Key, hard-won design decisions (do not regress these without reason):

- **Edge-detection V2 (opt-in, benchmark-gated; defaults stay legacy).** Three flags,
  flipped together by the `edge_v2()` context manager (the GUI's "Edge detection V2"
  checkbox routes each measure run through it; `V2_FLAGS` is the set):
  `EDGE_MODEL="erf"` adds a per-side blurred-step fit `I(y)=base+amp·Φ((y−μ)/σ)` per column
  as a THIRD candidate locus in the straightness contest (each side gets its own σ, so a
  skirted lower edge stops dragging its line; per-column confidence → `edge_conf_*`);
  `BG_MODE="pre-onset"` builds the background only from the jet-free padding frames at the
  folder start (count from `injection_meta.json`, written by `build_result`; silent fallback
  to the window median — the result key `bg_mode` reports what was actually used);
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
  check; the fit/angle is unaffected by the clip.
- Frames are selected by **jet-frame index** (`start..end`, default 10–20), counted from the
  first frame containing a jet (padding skipped) — measures the steady jet, skips the burst.
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

- **Windows-only paths and APIs** (SDK, `os.startfile`). Python 3.13, managed by **uv**:
  `uv sync` once creates `.venv/` from `pyproject.toml` + `uv.lock` (dev group includes
  pytest + PyInstaller); prefix commands with `uv run`.
- Run module CLIs with `uv run python -m hsc.<module>` from the repo root; the package is never
  pip-installed (`tool.uv.package = false` — it runs in place).
- Capture needs the IMV SDK + camera; **measurement does not** (pure cv2/scipy/sklearn on saved
  images), so you can iterate on `hsc/injection_extract.py` / `hsc/measure_angle.py` without hardware.
- BMP frames here are uncompressed 8-bit, often read fast via `injection_extract._bmp_info`
  (header parse) + `np.fromfile` instead of PIL/cv2 decode.
- All three motion back-ends must produce the **same** signal — verify equality if you touch them.
- Don't break the GUI contracts: `measure_folder(source, dest_base, start, end, progress)` and
  `injection_extract.detect_bounds_with_presence(...)` / `build_result(...)` are called by
  `hsc/gui/` (measurement.py, extraction.py, camera_worker.py).

## How to verify changes

- Tests: `uv run python -m pytest` (62 tests: import smoke, GUI wiring/dispatch, synthetic wedge,
  edge-detection V2 (erf/pre-onset/quality/pooled/toggle), calibration load, vendor layout,
  data root). Compile check:
  `uv run python -m py_compile hsc/*.py hsc/gui/*.py benchmark/*.py run_gui.py`.
- Edge-detection accuracy: `uv run python -m benchmark.run_benchmark <tag>` writes
  `benchmark/results/<tag>.csv` (synthetic wedges with exact ground truth); compare against
  the committed `benchmark/baseline.csv` (legacy scores). Flip flags via
  `measure_angle.edge_v2()` or per-flag module attributes for what-if runs.
- Measurement: run `uv run python -m hsc.measure_angle` on an existing `data\injection images\<run>`
  folder; render a
  saved frame (native 320×240 by default; raise `MEASURE_RENDER_SCALE` for a zoomable 960×720)
  and inspect that the green lines sit on the white jet edges.
  Reading an annotated `.bmp` requires converting to PNG first to view it.
- The Tk GUI and live camera can't run in a headless/agent environment — verify logic and
  saved-image output, and ask the user to confirm the GUI flow on the rig.

## Do / don't

- **Do** keep changes minimal and preserve the iteratively-tuned defaults (`EDGE_*`, `RANSAC_*`,
  `NOZZLE_SIDE`, `MEASURE_START/END`, padding). They reflect real user feedback on this rig.
- **Don't** commit, push, or add/upgrade dependencies unless asked. (Everything needed is in
  `pyproject.toml`/`uv.lock`; `uv sync` recreates the environment.)
- **Don't** delete the user's `data\captures\`, `data\injection images\`, or `data\measure\`
  data, or the hand-drawn reference images, without explicit instruction.
