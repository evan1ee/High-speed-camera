# Data Formats, Schemas & File Layouts

This document defines the exact schemas, serialization structures, and format specifications for all JSON metadata files, CSV report tables, image formats, and atomic file operations used across the system.

---

## 1. JSON Configuration & Metadata Schemas

All configuration and metadata files are stored as UTF-8 encoded JSON.

### 1.1 Spatial Calibration (`calibration.json`)
Stored in `settings/calibration.json` (or `data/calibration.json`). Managed atomically with an adjacent `.bak` backup.

```json
{
  "mm_per_px": 0.052341,
  "ref_mm": 5.0,
  "distance_px": 95.527,
  "edge1": {
    "horizontal": true,
    "k": 0.00142,
    "b": 42.15,
    "roi": [10, 30, 110, 55]
  },
  "edge2": {
    "horizontal": true,
    "k": 0.00139,
    "b": 137.68,
    "roi": [10, 125, 110, 150]
  },
  "mode": "step",
  "image_size": [320, 240],
  "created_at": "2026-08-12 14:05:30"
}
```

| Field | Type | Description |
| :--- | :--- | :--- |
| `mm_per_px` | `float` | Physical millimetres per pixel ($ref\_mm / distance\_px$). |
| `ref_mm` | `float` | Known physical gauge block reference dimension in mm. |
| `distance_px`| `float` | Perpendicular pixel distance between the two fitted edge lines. |
| `edge1`, `edge2`| `object` | Line equations ($y = kx + b$ for horizontal, $x = ky + b$ for vertical) and search ROIs. |
| `mode` | `string` | Edge detection polarity: `"step"`, `"outer"`, `"dark"`, `"bright"`. |
| `image_size` | `[int, int]` | Frame dimensions $[W, H]$ at calibration capture time. |

---

### 1.2 Nozzle Reference Lines (`reference_lines.json`)
Stored in `settings/reference_lines.json` (or `data/reference_lines.json`). Defines the spray coordinate system.

```json
{
  "red_p0": [305, 85],
  "red_p1": [305, 155],
  "blue_a": [305.0, 120.0],
  "blue_b": [0.0, 120.0],
  "rect": [285.87, 112.59, 180.72, 127.41],
  "rect_mm": {
    "near_mm": 1.0,
    "far_mm": 6.51,
    "height_mm": 0.775
  },
  "image_size": [320, 240],
  "created_at": "2026-08-12 14:10:15"
}
```

| Field | Type | Description |
| :--- | :--- | :--- |
| `red_p0`, `red_p1` | `[int, int]` | Endpoints of the user-drawn nozzle tip edge line. |
| `blue_a`, `blue_b` | `[float, float]`| Start (tip midpoint) and end points of the spray centerline axis. |
| `rect` | `[float, float, float, float]` | Bounding box of the target rectangle in pixels: $[x_0, y_0, x_1, y_1]$. |
| `rect_mm` | `object` | Physical dimensions of the tolerance rectangle in mm. |
| `image_size` | `[int, int]` | Capture resolution at which the reference was marked. |

---

### 1.3 Injection Window Metadata (`injection_meta.json`)
Written into `data/injection images/<run>/` by the extraction module.

```json
{
  "source_dir": "data/captures/2026-08-12-14-15-00_320x240",
  "onset_frame": 1842,
  "end_frame": 2085,
  "peak_frame": 1856,
  "pre_frames": 30,
  "post_frames": 30,
  "copy_start": 1812,
  "copy_end": 2115,
  "extracted_count": 304,
  "total_burst_frames": 4192,
  "end_rule": "presence"
}
```

| Field | Type | Description |
| :--- | :--- | :--- |
| `onset_frame` | `int` | Zero-based index in the raw burst where injection starts. |
| `end_frame` | `int` | Zero-based index where the jet clears or motion ceases. |
| `peak_frame` | `int` | Frame exhibiting maximum temporal motion. |
| `pre_frames` | `int` | Number of padding frames prepended ahead of onset (default: 30). |
| `post_frames`| `int` | Number of padding frames appended after the end (default: 30). |
| `copy_start` | `int` | First frame copied into the injection folder ($onset - pre$). |
| `copy_end` | `int` | Last frame copied into the injection folder ($end + post$). |
| `end_rule` | `string` | End detection policy used: `"presence"` or `"temporal"`. |

---

### 1.4 Piston Metadata (`piston_meta.json`)
Superset of `injection_meta.json` created in `data/injection images/<run>/` for piston tracking runs.

```json
{
  "source_dir": "data/captures/piston_2026-08-12-14-20-00_320x240",
  "onset_frame": 1250,
  "end_frame": 1410,
  "peak_frame": 1265,
  "pre_frames": 30,
  "post_frames": 30,
  "copy_start": 1220,
  "copy_end": 1440,
  "extracted_count": 221,
  "fps": 1048.2,
  "frame_times_us": [0, 954, 1908, 2862, 3816],
  "barrel_profile": {
    "row_lo": 68,
    "row_hi": 165,
    "dark": 32.5,
    "bright": 242.0,
    "thresh": 137.25
  }
}
```

---

### 1.5 Hardware Capture Metadata (`piston_capture.json`)
Written directly into the raw burst folder (`data/captures/piston_<run>/`) during `Capture Piston` acquisition.

```json
{
  "fps": 1048.24,
  "duration_s": 4.0,
  "frame_count": 4193,
  "dropped_frames": 0,
  "frame_times_us": [1284560010, 1284560964, 1284561918],
  "block_ids": [10024, 10025, 10026]
}
```

---

## 2. CSV Report Table Specifications

### 2.1 Spray Angle CSV Report (`<run>_angles.csv`)
Saved in `data/measure/<run>/<run>_angles.csv`.

#### Structure:
1. **Header row**: Column labels.
2. **Per-frame data rows**: One row per measured frame (sorted by frame filename).
3. **Summary rows**: Aggregated statistics.

#### Sample Content:
```csv
frame,angle_deg,k_upper,k_lower,n_points,rms_up_px,rms_lo_px,coverage,span_ratio,quality,confidence,q_up,q_lo,policy,in_rect
frame_000040.bmp,0.44,-0.00768,0.00012,215,0.182,0.214,0.995,0.982,88,High,92,85,max,OK
frame_000041.bmp,0.42,-0.00732,-0.00005,214,0.195,0.220,0.991,0.980,86,High,90,83,max,OK
mean,0.43,,,,,,,,,,,,
std,0.014,,,,,,,,,,,,
trusted_mean,0.43,,,10,,,,,,,,,excl. Low frames
pooled_angle,0.42,,,2145,,,,,,,,,all-frame fit
run_confidence,High (87),,,,,,,,,,,,
```

| Column | Unit | Description |
| :--- | :--- | :--- |
| `frame` | String | Frame filename (`frame_000040.bmp`). |
| `angle_deg` | Degrees | Reported angle (deviation from centerline, or edge-to-edge). |
| `k_upper`, `k_lower` | Slope | Slopes of upper and lower fitted green lines. |
| `n_points` | Integer | Total edge points in ROI used for the fits. |
| `rms_up_px`, `rms_lo_px`| Pixels | Robust RMS residual of raw subpixel points vs fitted line. |
| `coverage` | Fraction | Fraction of ROI columns that produced valid edge samples ($0.0\dots1.0$). |
| `span_ratio` | Fraction | Length of jet this frame relative to maximum jet length in run. |
| `quality` | $0\dots100$ | Overall frame quality score: $\min(S_{\text{fit}}, S_{\text{cov}}, S_{\text{span}})$. |
| `confidence`| String | Categorical confidence: `"High"`, `"Medium"`, `"Low"`. |
| `q_up`, `q_lo` | $0\dots100$ | Individual edge quality scores. |
| `policy` | String | Angle resolution policy applied (`"max"`, `"upper-only"`, `"lower-only"`). |
| `in_rect` | String | Jet containment verdict: `"OK"`, `"NG"`, or blank if no reference. |

---

### 2.2 Piston Speed & Hydrodynamics CSV Report (`<run>_speed.csv`)
Saved in `data/measure/<run>/<run>_speed.csv`.

#### Sample Content:
```csv
frame,time_ms,x_px,distance_px,distance_mm,speed_mm_s,speed_m_s,k,n_points,rms_px,coverage,at_border,stable
frame_000030.bmp,0.000,42.15,0.00,0.00,0.0,0.000,0.0021,88,0.21,0.98,False,True
frame_000031.bmp,0.954,43.20,1.05,0.05,58.2,0.058,0.0021,88,0.22,0.98,False,True
frame_000032.bmp,1.908,45.85,3.70,0.19,142.6,0.143,0.0021,87,0.20,0.97,False,True
stroke_mm,12.45
peak_speed_mm_s,165.2
duration_ms,142.3
peak_jet_speed_m_s,257.8
peak_jet_pressure_MPa,33.2
```

| Column / Key | Unit | Description |
| :--- | :--- | :--- |
| `time_ms` | Milliseconds | Elapsed physical time from stroke start. |
| `x_px` | Pixels | Fitted piston edge column at barrel center row. |
| `distance_mm` | Millimetres | Net axial displacement from reference start frame ($d_{\text{px}} \times \text{mm/px}$). |
| `speed_mm_s` | $\text{mm/s}$ | Savitzky-Golay numerical derivative of displacement. |
| `k` | Slope | Piston face tilt (fixed across stroke via common slope pooling). |
| `stable` | Boolean | `False` if step $> 10\ \text{px}$ (implausible detector hop); `True` otherwise. |
| `stroke_mm` | Millimetres | Total stroke travel distance from rest to bottom-out. |
| `peak_speed_mm_s` | $\text{mm/s}$ | Maximum instantaneous piston speed achieved during stroke. |
| `duration_ms` | Milliseconds | Total stroke duration from initial motion to plateau. |
| `peak_jet_speed_m_s`| $\text{m/s}$ | Peak exit velocity: $v_{\text{piston}} (D_{\text{barrel}} / D_{\text{orifice}})^2$. |
| `peak_jet_pressure_MPa`| $\text{MPa}$ | Stagnation impact pressure: $\frac{1}{2}\rho v_{\text{jet}}^2$. |

---

### 2.3 Cross-Run Summary CSV (`summary_<timestamp>.csv`)
Saved in `data/measure/summary_<timestamp>.csv`.

#### Structure:
1. Per-run breakdown table.
2. Aggregate descriptive statistics table ($n, \text{mean}, \text{std}, \mathbf{CV\%}, \min, \text{median}, \max$).
3. Skipped folders audit table (records exact error reason for any folder that failed).

#### Sample Content:
```csv
run,stroke_mm,peak_speed_mm_s,duration_ms,peak_jet_speed_m_s,peak_jet_pressure_MPa
piston_run_01,12.45,165.2,142.3,257.8,33.2
piston_run_02,12.42,168.1,141.0,262.3,34.4
piston_run_03,12.48,164.5,143.5,256.7,32.9

metric,n,mean,std,cv_percent,min,median,max
stroke_mm,3,12.45,0.030,0.24,12.42,12.45,12.48
peak_speed_mm_s,3,165.9,1.90,1.15,164.5,165.2,168.1
duration_ms,3,142.3,1.25,0.88,141.0,142.3,143.5
peak_jet_speed_m_s,3,258.9,2.98,1.15,256.7,257.8,262.3
peak_jet_pressure_MPa,3,33.5,0.79,2.37,32.9,33.2,34.4

skipped_folder,reason
piston_corrupted,No piston speed CSV in piston_corrupted
```

---

## 3. Image File & Directory Standards

### 3.1 Raw BMP Structure & Row Order
Raw high-speed bursts and extracted frames are stored as uncompressed 8-bit Windows Bitmap (`.bmp`) files.
- **Header**: Standard 54-byte BMP header (14-byte `BITMAPFILEHEADER` + 40-byte `BITMAPINFOHEADER`).
- **Color Table**: 1,024 bytes (256 entries $\times$ 4 bytes RGBA grayscale palette).
- **Pixel Offset**: Header offset is typically $54 + 1024 = 1078$ bytes.
- **Row Order Convention (`biHeight` Sign)**:
  - Standard Windows / OpenCV `cv2.imwrite`: `biHeight > 0` (Bottom-up: first stored row is the bottom of the image).
  - IMV SDK `IMV_SaveImageToFile`: `biHeight < 0` (Top-down: first stored row is the top of the image).
  - **Requirement**: Any custom BMP loader (C++ or Python) must inspect `biHeight`. If positive, reverse the rows (`[::-1]` or vertical flip) after reading to prevent the jet from appearing upside down.

### 3.2 File & Directory Naming Conventions
- Frame names: `frame_000001.bmp` (6-digit zero-padded index, 1-based).
- Burst folders: `yyyy-mm-dd-hh-mm-ss_<aspect>[_<label>]` (e.g. `2026-08-12-14-07-22_320x240_deviceA`).
- Piston burst prefix: `piston_yyyy-mm-dd-hh-mm-ss_<aspect>[_<label>]`.
- Gel burst prefix: `gel_yyyy-mm-dd-hh-mm-ss_<aspect>[_<label>]`.
- Monitor event folders: `monitor_yyyy-mm-dd-hh-mm-ss_<aspect>[_<label>]`.
- **Destination Collision Handling**: If a folder already exists, append counter suffix `_2`, `_3`, etc. (`make_dest_dir`).

---

## 4. Atomic File Operations

To prevent configuration corruption during power loss or application abort:
1. `calibration.json` and `reference_lines.json` are written using an atomic write pattern:
   - If target exists, copy to `<filename>.bak`.
   - Write new payload to a temporary file in the same directory (`<filename>.tmp`).
   - Atomically rename `os.replace("<filename>.tmp", "<filename>")` (POSIX `rename` / Windows `MoveFileEx` with `MOVEFILE_REPLACE_EXISTING`).
