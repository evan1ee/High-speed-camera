# High-Speed Camera — Needle-Free Injector Spray-Angle Toolkit

Capture a high-pressure water-jet injection with a high-speed camera, automatically
isolate the ~200–300 frames that contain the injection out of the thousands recorded,
and measure the spray (jet) angle on the frames that matter.

The whole flow runs from a single **Capture** click in the GUI:

```
Capture (burst)  ─►  Find Injection  ─►  Measure spray angle
 captures\…           injection images\…    measure\…
```

---

## What's in here

| File | Purpose |
|------|---------|
| `capture_gui.py` | **Main app.** Tkinter GUI: live preview, instant capture, auto find-injection, auto measure. |
| `capture_image.py` | Low-level camera capture (IMV SDK). Also a standalone CLI. |
| `injection_extract.py` | Finds the injection event in a long burst and copies the relevant frames out. |
| `injection_scan.cpp` / `injection_scan.exe` | Fast C++/OpenMP motion scanner used by `injection_extract` (optional; Python fallback exists). |
| `build_injection_scan.bat` | Rebuilds `injection_scan.exe` (MinGW g++). |
| `measure_angle.py` | Spray-angle measurement pipeline (Otsu → edges → RANSAC → angle). Also a CLI. |
| `measure_block.py` | Measures the angle of a reference **angle block** from a single still (same edge/RANSAC core). Also a CLI. |
| `Development/`, `Runtime/` | The camera vendor's IMV SDK (Python wrapper) and runtime DLLs. |
| `captures/` | Raw burst output (one timestamped folder per run). |
| `injection images/` | Extracted injection windows (one folder per run). |
| `measure/` | Annotated angle-measurement images + `angles.csv`. |

---

## Requirements

- **Windows** (the camera SDK and `os.startfile` are Windows-specific).
- **Python 3.13** with:
  ```
  pip install numpy opencv-python scipy scikit-learn pillow
  ```
- For **capturing**: the IMV camera connected, plus the bundled SDK in
  `Development/Samples/Python/IMV/MVSDK` and DLLs in `Runtime/x64` (already in the repo).
- For the **fast C++ scanner** (optional): MinGW `g++` on PATH. If `injection_scan.exe`
  is missing, the Python fallback is used automatically.

---

## Quick start (GUI)

```bash
python capture_gui.py
```

1. The window opens maximized and the **live preview** starts automatically.
2. Set the capture parameters (defaults shown):
   - **Capture time** `4.0` s, **Aspect preset** `320x240`, **Exposure** `500` µs, **Camera index** `1`.
   - **Frames before / after injection** `30 / 30` (padding kept around the detected event).
   - **Measure from / to (Nth)** `10 / 20` (which jet frames to measure — see below).
3. Click **Capture**, then fire the injector. When capture finishes it **auto-detects the
   injection** and **auto-measures** the spray angle.
4. Results land in `injection images\<run>\` and `measure\<run>\`. Use **Open Last Folder**.

Buttons: **Stop Preview**, **Capture**, **Stop** (abort), **Find Injection** (re-run on any
folder), **Measure** (pick a folder to measure), **Open Last Folder**.

---

## How it works

### 1. Capture (`capture_image.py`)
Free-run burst at the camera's max FPS. With **defer save** the frames are cloned in RAM
during the burst and written afterward, avoiding dropped frames at ~1000 FPS. Each run is
saved to `captures\<timestamp>_<aspect>\` as `frame_000001.bmp …`.

### 2. Find injection (`injection_extract.py`)
A burst has thousands of frames but only a short injection. The tool computes a per-frame
**temporal motion signal** (pixels changed vs. the previous frame), finds the sharp **onset**,
and the **end** via a jet-presence signal (so a steady jet isn't cut early). It then copies
`[onset − before … end + after]` into `injection images\<run>\`.
Motion signal back-ends, fastest first: **C++/OpenMP exe → NumPy raw-BMP → PIL** (all
identical). After a capture this runs **in memory** (no disk re-read).

### 3. Measure spray angle (`measure_angle.py`)
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

### 4. Measure an angle block (`measure_block.py`)
The **Measure Angle Block** button captures a single still of a reference block placed under
the camera and measures the angle between its two straight edges — a calibration/validation of
the same edge-finding used for the jet. Result images and `block_angles.csv` go to
`measure\angle_block\`.

### 4b. Spatial calibration — real size per pixel (`calibrate_scale.py`)

To know actual dimensions (mm) from the image, calibrate against a reference block whose
**two edges are a known distance apart** (e.g. 10 mm), placed at the **same working
distance as the jet**. Calibration uses an **ROI (region-of-interest) workflow** — you box
each edge and the software finds it to sub-pixel precision (robust against reflections and
the nozzle in the background):

**Auto (one click):** click **Auto Calibrate** — the GUI grabs a still (saved to `measure\block\`),
auto-detects the two dark lines in the **left third** of the image (which avoids the nozzle /
reflection clutter on the right), fits the two green lines, saves the calibration, and opens the
annotated check image. Just confirm the green lines land on the outer edge of each dark line.

**Manual (draw ROIs):** if the auto detection picks the wrong lines, use **Calibrate Scale**:

1. Enter the edge-to-edge distance in **Cal. distance (mm)** and click **Calibrate Scale** —
   the GUI grabs a still and opens the calibration window.
2. Drag a box (ROI) around the **upper edge**, then a box around the **lower edge**.
3. Click **Detect Edge**. A green line is fitted inside each ROI; the window shows the
   **pixel distance** and **mm/pixel**. If a green line is off, redraw that ROI and detect again.
4. Click **Save Calibration** — writes `calibration.json` and a `*_scale.bmp` check image.

**Measuring another block** (after calibrating): replace the reference with an unknown block and
click **Measure Block** — it detects the two edges the same way and reports the block's size in
**mm** using the stored calibration, *without* changing it (writes a `*_measured.bmp` overlay).
Note: **Auto Calibrate / Calibrate Scale always save a new calibration** (they assume the block is
the entered distance), so to measure an unknown block you must calibrate on the **known reference
first**, then use **Measure Block** — don't click Calibrate on the unknown block.

Inside each ROI: `Gaussian blur → per-scanline sub-pixel edge → TLS line fit`. Because a
chamfered block edge appears as a **dark line** (the chamfer reflects light away from the
camera), the detector locates the **outer boundary of each dark line** — the true block edge —
not the line centre (`--mode outer`, the default; `dark`/`bright`/`step` are also available).
The perpendicular distance between the two fitted lines is the reference length in pixels, so
`mm_per_px = distance_mm / distance_px`. (CLI for scripting:
`python calibrate_scale.py still.bmp --ref-mm 10 --roi1 x0 y0 x1 y1 --roi2 x0 y0 x1 y1`.)
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

| Aspect | Water jet (`measure_angle.py`) | Angle block (`measure_block.py`) |
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
# List cameras / capture a burst
python capture_image.py --list
python capture_image.py --duration 4 --aspect 320x240 --exposure-us 500

# Find the injection in a burst folder
python injection_extract.py "captures\<run>" --before 30 --after 30

# Measure a folder of injection frames (jet frames 10..20), or a single image
python measure_angle.py "injection images\<run>" --start 10 --end 20
python measure_angle.py frame_002780.bmp        # single image -> *_measured.png

# Measure an angle block from a still image
python measure_block.py measure\angle_block\block_<timestamp>.bmp
```

---

## Tuning knobs

`measure_angle.py`:
- `NOZZLE_SIDE` — `+1` nozzle on the right (default), `-1` on the left.
- `NOZZLE_SKIP` / `ROI_FRAC` — exclude the nozzle origin and the far breakup region.
- `RANSAC_RESIDUAL` — inlier tolerance (px) for the line fit.
- `EDGE_PAD` / `EDGE_SMOOTH` — edge search band and column smoothing.
- `MEASURE_START` / `MEASURE_END` — default jet-frame range.
- `SUPERSAMPLE`, `LINE_COLOR`, `APEX_GAP` — render scale, line color, nozzle gap.

`injection_extract.py`: `DIFF_THRESH`, `END_RESIDUAL_K`, `DOWNSAMPLE`, before/after padding.
