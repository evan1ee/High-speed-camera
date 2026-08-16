# High-Speed Camera — Needle-Free Injector Spray-Angle Toolkit

Capture a high-pressure water-jet injection with a high-speed camera, automatically
isolate the ~200–300 frames that contain the injection out of the thousands recorded,
and measure the spray (jet) angle on the frames that matter.

The flow is three stages:

```
Capture (burst)  ─►  Find Injection  ─►  Measure spray angle
 data\captures\…      data\injection images\…   data\measure\…
```

> **The Tkinter desktop app was retired on 2026-08-17.** The rig is now driven by the
> **HTTP/WebSocket service** (`uv run python -m hsc.api`) and by the module CLIs below.
> The service chains the **piston-speed** pipeline end to end; the spray-angle pipeline runs
> from its CLIs. Live preview, Monitor mode and the interactive calibration/reference dialogs
> have no driver until the React UI lands — git history holds the dialogs for that port.

---

## What's in here

| File | Purpose |
|------|---------|
| `hsc/api/` | **Entry point** — the rig service (`uv run python -m hsc.api --host <ip>`): REST, `/ws/events`, `/ws/preview`. |
| `hsc/rig/` | The service core: camera worker, pipeline jobs, control lease, event bus, SQLite run store. No web framework. |
| `hsc/hardware/` | The camera seam: protocol, real IMV adapter, and a fake camera that replays a saved burst. |
| `hsc/capture_image.py` | Low-level camera capture (IMV SDK). Also a standalone CLI. |
| `hsc/injection_extract.py` | Finds the injection event in a long burst and copies the relevant frames out. |
| `native/injection_scan.cpp` / `vendor/bin/injection_scan.exe` | Fast C++/OpenMP motion scanner used by `injection_extract` (optional; Python fallback exists). |
| `native/build_injection_scan.bat` | Rebuilds `injection_scan.exe` into `vendor\bin\` (MinGW g++). |
| `hsc/measure_angle.py` | Spray-angle measurement pipeline (Otsu → edges → RANSAC → angle). Also a CLI. |
| `hsc/measure_block.py` | Measures the angle of a reference **angle block** from a single still (same edge/RANSAC core). Also a CLI. |
| `hsc/piston_track.py`, `hsc/measure_piston.py` | Piston edge tracking and the distance/speed record of the stroke. Also CLIs. |
| `vendor/Development/`, `vendor/Runtime/` | The camera vendor's IMV SDK (Python wrapper) and runtime DLLs. |
| `data\captures\` | Raw burst output (one timestamped folder per run). |
| `data\injection images\` | Extracted injection windows (one folder per run). |
| `data\measure\` | Annotated angle-measurement images + `angles.csv`. |

---

## Requirements

- **Windows** (the camera SDK and `os.startfile` are Windows-specific).
- **[uv](https://docs.astral.sh/uv/)** — manages Python 3.13 and all dependencies
  (numpy, opencv-python, scipy, scikit-learn, pillow, fastapi, uvicorn; dev group adds
  pytest and friends).
  One-time setup from the repo root:
  ```
  uv sync
  ```
  Then prefix every command with `uv run` (as shown below).
- For **capturing**: the IMV camera connected, plus the bundled SDK in
  `vendor/Development/Samples/Python/IMV/MVSDK` and DLLs in `vendor/Runtime/x64` (already in the repo).
- For the **fast C++ scanner** (optional): MinGW `g++` on PATH. If `vendor\bin\injection_scan.exe`
  is missing, the Python fallback is used automatically.

---

## Quick start — the rig service

```bash
uv run python -m hsc.api --host 100.x.y.z --port 8000
```

Bind to the **Tailscale address** on the rig. There is no application-level authentication:
the tailnet is the security boundary, so anyone on it can fire the injector. Flags:
`--data-root` (where `captures\`, `injection images\`, `measure\` and `rig.db` live),
`--spa <built frontend dir>`, `--cors <origin>` (repeatable, for frontend development).

A client takes the **control lease**, posts a piston-capture job, and follows it on
`/ws/events`; the service runs **capture → find stroke → measure piston → video** and records
the run in SQLite. Runs, their CSVs and their media are served back over REST.

## Quick start — analysis from the command line

Measurement needs no camera and no server:

```bash
uv run python -m hsc.capture_image --duration 4 --aspect 320x240 --exposure-us 500
uv run python -m hsc.injection_extract "data\captures\<run>" --before 30 --after 30
uv run python -m hsc.measure_angle "data\injection images\<run>" --start 10 --end 20
```

**Smart save** (`hsc/smart_save.py`) is the *detect-before-write* capture path: detect the
injection in RAM *before* saving and write only the `before..after` window straight to
`data\injection images\<run>\` (plus an `injection_meta.json`), skipping the full-burst write
to `data\captures\`. It has **no live driver today** — the service writes the full burst — but
its decision can still be validated against recorded bursts:
`uv run python -m hsc.smart_save "data\captures\<run>" --compare` should report `IDENTICAL`
(the same window the offline extractor picks).

## Monitor mode (continuous multi-injection capture)

**No driver today** — monitoring was started from the retired GUI, and nothing restarts a
session until the web UI grows one. The detector itself (`hsc/monitor.py`) is kept, tested and
still replayable from the CLI, because its thresholds were calibrated on the rig.

When driven, the camera streams continuously: every injection is detected **online**, saved by
a background writer to its own `data\injection images\monitor_<stamp>_<WxH>\` folder (with
`injection_meta.json`; nothing is written to `data\captures\`), and then measured — one event
at a time, in order, even if the next injection is fired while the previous one is still
processing. A typical saved event is ~150–300 frames (`before` + jet + `after`). Stopping
closes, saves and processes any event in progress.

How detection works (calibrated on-rig 2026-07-10): an event **triggers** when one frame
changes > `MON_TRIGGER` (300) pixels; it **ends** when the changed-pixel count stays quiet
(≤ `max(30, 0.005 × event peak)`) for `MON_END_HOLD` (60) consecutive frames — a flowing jet
changes hundreds–thousands of pixels per frame, a wet-but-still scene ~0–25; and at close the
event is **validated**: a peak below `MON_MIN_PEAK` (3000) pixels is a drip/mist disturbance
and is ignored (logged, not saved). Real injections on this rig peak at 6k–55k changed pixels,
junk at ≤760.

Camera-safety note: continuous streaming is the sensor's normal duty cycle — the live preview
already streams continuously and there is no mechanical shutter. Sustained max-FPS streaming
just runs the camera warm (which adds a little image noise), so keep it ventilated.

Validate the online detector against the offline one on your own recorded bursts:

```bash
uv run python -m hsc.monitor "data\captures\<run>" --compare   # expect: OK
```

---

## How it works

### 1. Capture (`hsc/capture_image.py`)
Free-run burst at the camera's max FPS. With **defer save** the frames are cloned in RAM
during the burst and written afterward, avoiding dropped frames at ~1000 FPS. Each run is
saved to `data\captures\<timestamp>_<aspect>\` as `frame_000001.bmp …`.

### 2. Find injection (`hsc/injection_extract.py`)
A burst has thousands of frames but only a short injection. The tool computes a per-frame
**temporal motion signal** (pixels changed vs. the previous frame), finds the sharp **onset**,
and the **end** via a jet-presence signal (so a steady jet isn't cut early). It then copies
`[onset − before … end + after]` into `data\injection images\<run>\`.
Motion signal back-ends, fastest first: **C++/OpenMP exe → NumPy raw-BMP → PIL** (all
identical). After a capture this runs **in memory** (no disk re-read).

### 3. Measure spray angle (`hsc/measure_angle.py`)
Canonical high-speed-imaging pipeline:

```
Gaussian blur → Otsu threshold → largest connected component →
column-wise edge extraction → Savitzky–Golay smoothing → ROI selection →
RANSAC line fitting → spray-angle = |atan(k_upper) − atan(k_lower)|
```

- A per-pixel **temporal-median background** is subtracted first so Otsu sees only the jet
  (the static nozzle/holder is removed).
- The edge per column is the **steepest intensity gradient on the raw image within the jet
  band**, so the lines sit on the visible white edge even when the jet is asymmetric.
- The two **green** edge lines and the angle are drawn (3× supersampled, anti-aliased) and
  saved, plus `angles.csv` with `angle_deg, k_upper, k_lower, n_points` per frame and the mean.

"Measure from/to (Nth)" counts from the **first frame that actually contains a jet**
(pre-injection padding is skipped), so the default `10–20` measures the steady jet and skips
the violent initial burst.

**Edge detection V2 (opt-in A/B):** wrapping a measure run in `measure_angle.edge_v2()` applies
a benchmark-gated upgrade — a per-side blurred-step (erf) edge model, a pre-onset background
built only from the jet-free padding frames, and a trusted-edge angle policy. Off (default)
= the unchanged legacy pipeline; measure the same folder twice to compare. `angles.csv`
also gains per-edge quality columns (`q_up,q_lo,policy`) and a `pooled_angle` summary row
(one fit over all measured frames' edge samples).

### 4. Measure an angle block (`hsc/measure_block.py`)
Takes a single still of a reference block placed under
the camera and measures the angle between its two straight edges — a calibration/validation of
the same edge-finding used for the jet. Result images and `block_angles.csv` go to
`data\measure\angle_block\`.

### 4b. Spatial calibration — real size per pixel (`hsc/calibrate_scale.py`)

To know actual dimensions (mm) from the image, calibrate against a reference block whose
**two edges are a known distance apart** (e.g. 10 mm), placed at the **same working
distance as the jet**. Calibration uses an **ROI (region-of-interest) workflow** — you box
each edge and the software finds it to sub-pixel precision (robust against reflections and
the nozzle in the background):

**Auto:** `auto_calibrate_image` (`auto_rois`) auto-detects the two block edges in the
**left third** of a still — which avoids the nozzle / reflection clutter on the right — fits
the two green lines, and saves the calibration plus an annotated check image to
`data\measure\block\`. Confirm the green lines land on the correct edge of each line.

**Manual:** if auto-detection picks the wrong lines, pass the two ROIs explicitly:

```bash
uv run python -m hsc.calibrate_scale still.bmp --ref-mm 5 \
    --roi1 x0 y0 x1 y1 --roi2 x0 y0 x1 y1
```

A green line is fitted inside each ROI, and the **pixel distance** and **mm/pixel** are
reported and written to `calibration.json` with a `*_scale.bmp` check image. If a green line
is off, adjust that ROI and re-run.

> The interactive dialog that let you drag the ROIs on screen went with the Tk app; it is in
> git history and returns with the React UI.

**Measuring another block** (after calibrating): replace the reference with an unknown block
and use `measure_block_size` — it detects the two edges the same way and reports the block's
size in **mm** using the stored calibration, *without* changing it (writes a `*_measured.bmp`
overlay). Note: **calibration always saves a new `calibration.json`** (it assumes the block is
the entered distance), so to measure an unknown block, calibrate on the **known reference
first**, then measure — never calibrate on the unknown block.

Inside each ROI: `Gaussian blur → per-scanline sub-pixel edge → TLS line fit`. Because a
chamfered block edge appears as a **dark line** (the chamfer reflects light away from the
camera), the detector locates the **outer boundary of each dark line** — the true block edge —
not the line centre (`--mode outer`, the default; `dark`/`bright`/`step` are also available).
The perpendicular distance between the two fitted lines is the reference length in pixels, so
`mm_per_px = distance_mm / distance_px`. (CLI for scripting:
`uv run python -m hsc.calibrate_scale still.bmp --ref-mm 10 --roi1 x0 y0 x1 y1 --roi2 x0 y0 x1 y1`.)
The scale stays valid while lens, zoom and working distance are unchanged (the aspect preset
does not affect it — cropping changes the field of view, not the pixel size). Re-calibrate
after any refocus/reposition.

### 5. Line quality & measurement confidence

Every measured jet frame is scored 0–100 against three criteria (the score is the
**minimum** of the three — a measurement is only as good as its weakest aspect):

| Criterion | What it checks | 100 at | 0 at |
|-----------|----------------|--------|------|
| **fit** (`rms_up_px`/`rms_lo_px`) | Robust RMS of the raw subpixel edge points vs the drawn line — is the detected edge straight and clean? | ≤ 0.25 px | ≥ 1.0 px |
| **coverage** | Fraction of ROI columns that produced an edge point — gaps mean mist/dropout | ≥ 0.98 | ≤ 0.80 |
| **span** (`span_ratio`) | This frame's jet length vs the longest in the run — a shrinking jet means the injection is **decaying** and its angle is unreliable | ≥ 0.92 | ≤ 0.60 |

Score ≥ 75 → **High**, ≥ 50 → **Medium**, else **Low**. The confidence is drawn on each
annotated image (green/yellow/red), written per frame to `angles.csv`, and the run gets an
overall confidence = min(median frame score, angle-repeatability score from the std).
`angles.csv` also reports a **trusted_mean** computed only from non-Low frames, so
decay-phase frames can't drag the result. If a run comes back **Low**, the usual cause is
that the measured window (`Measure from/to`) ran into the end of the injection — lower the
window or check `span_ratio` in the CSV to see where the jet collapsed.

---

## Jet vs. angle-block: what's the same, what differs

Both measurements share the **same core**: segment the bright object (largest connected
component), find its two edges by the **steepest intensity gradient on the raw image**, fit
each edge with **RANSAC**, and report `angle = |atan(k_upper) − atan(k_lower)|`. The
differences are only in how the object is isolated and the geometry assumed:

| Aspect | Water jet (`hsc/measure_angle.py`) | Angle block (`hsc/measure_block.py`) |
|--------|--------------------------------|----------------------------------|
| Input | A **sequence** of frames; picks jet frames `start..end` (default 10–20) | A **single still** image |
| Background | Subtracts a **temporal-median background** to isolate the moving jet and remove the static nozzle | **None** — Otsu runs directly on the blurred raw image |
| Segmentation input | Otsu on the background-subtracted difference | Otsu on the raw grayscale |
| Orientation | Assumes horizontal jet, **nozzle on the right** (`NOZZLE_SIDE`) | **Auto** — horizontal or vertical (transposes if needed); no fixed side |
| ROI / smoothing | Excludes the nozzle gap and far breakup region; **Savitzky–Golay** edge smoothing | **No ROI, no Savitzky–Golay** — full block length, RANSAC for robustness |
| Line drawing | From a gap near the nozzle out to the image edge | Across the **full block length**; vertex dot only if in frame |
| Output | Per-frame `angles.csv` + mean | Appends to `block_angles.csv` |

In short: the jet needs background subtraction, frame selection, a nozzle-anchored ROI and edge
smoothing because it is a faint, transient, cone-shaped stream in a noisy sequence; the angle
block is a solid, static object in one still, so it skips all of that, auto-orients, and fits
its two full-length edges — but both find the edges the same way and compute the angle
identically.

---

## Command line

```bash
# Run all CLIs as modules from the repo root (the package is never pip-installed)

# List cameras / capture a burst
uv run python -m hsc.capture_image --list
uv run python -m hsc.capture_image --duration 4 --aspect 320x240 --exposure-us 500

# Find the injection in a burst folder
uv run python -m hsc.injection_extract "data\captures\<run>" --before 30 --after 30

# Measure a folder of injection frames (jet frames 10..20), or a single image
uv run python -m hsc.measure_angle "data\injection images\<run>" --start 10 --end 20
uv run python -m hsc.measure_angle frame_002780.bmp    # single image -> *_measured.png

# Measure an angle block from a still image
uv run python -m hsc.measure_block "data\measure\angle_block\block_<timestamp>.bmp"
```

---

## Tuning knobs

`hsc/measure_angle.py`:
- `NOZZLE_SIDE` — `+1` nozzle on the right (default), `-1` on the left.
- `NOZZLE_SKIP` / `ROI_FRAC` — exclude the nozzle origin and the far breakup region.
- `RANSAC_RESIDUAL` — inlier tolerance (px) for the line fit.
- `EDGE_PAD` / `EDGE_SMOOTH` — edge search band and column smoothing.
- `MEASURE_START` / `MEASURE_END` — default jet-frame range.
- `SUPERSAMPLE`, `LINE_COLOR`, `APEX_GAP` — render scale, line color, nozzle gap.

`hsc/injection_extract.py`: `DIFF_THRESH`, `END_RESIDUAL_K`, `DOWNSAMPLE`, before/after padding.

---

## Tests

```bash
uv run python -m pytest
```

395 tests: module imports, the measurement pipeline on a synthetic wedge,
injection-bounds detection + copy-window clamping, equivalence of the three
motion-signal back-ends (C++ / NumPy raw-BMP / PIL), piston tracking and speed against
synthetic strokes with exact ground truth, and the whole service layer (fake camera, store,
jobs, REST routes, both WebSockets, layering guard). No camera and no server are needed —
nothing binds a port. The service layers are additionally held at **100% coverage**:

```bash
uv run python -m pytest --cov=hsc.hardware --cov=hsc.rig --cov=hsc.api --cov-fail-under=100
```

Tests that depend on rig data (`data/` is git-ignored) skip cleanly when it is absent.

---

## Recovery

- **Reset calibration / reference:** delete `settings\calibration.json` or
  `settings\reference_lines.json` to clear a bad calibration or nozzle reference, then
  re-run the calibration CLI / `set_reference_from_image`. After any re-save a `.bak` of the
  previous version sits next to each file (writes are atomic, so a crash mid-save
  can't corrupt them).
- **Logs:** the service logs to its console (uvicorn); each run's numbers live in its
  `data\measure\<run>\` folder and in `rig.db`.
- **Packaging:** the frozen one-folder Windows build was retired with the GUI it packaged.
  See `docs/DISTRIBUTION.md` for running from source until the web build replaces it.
