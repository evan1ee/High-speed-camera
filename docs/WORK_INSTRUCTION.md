# High Speed Camera — Work Instruction

**Needle-free injector test rig — capture and measurement**

| | |
|---|---|
| Application | `HighSpeedCamera.exe` |
| Document version | 1.0 — 2026-09-17 |
| Applies to | Spray angle, piston speed, gel injection, monitoring |

---

## 1. What this app does

A high-speed camera watches a needle-free injector fire. The app records a short
burst of images, finds the few milliseconds that actually contain the injection,
and measures it.

There are **four jobs** it can do. Each is one button, and each runs its whole
sequence automatically once you press it.

| Job | Button | What you get |
|---|---|---|
| Spray angle | **Capture** | Angle of the jet vs the nozzle axis, per frame + a mean |
| Piston speed | **Capture Piston** | Distance/speed vs time for the piston stroke, plus jet speed and pressure |
| Gel injection | **Capture Gel Injection** | The injection images and a slow-motion video (no angle measurement) |
| Repeatability | **Start Monitoring** | Many injections in a row, each measured automatically |

> **The camera is black and white.** There is no colour mode. Anything you need
> to see must differ in **brightness**, not in hue. A dye that is a different
> colour but the same lightness is invisible to this camera.

---

## 2. Before you start

### 2.1 Every session

1. Connect the camera and start the app (`HighSpeedCamera.exe`).
2. The **Live Preview** starts automatically. Check the image is in focus and
   the injector is in frame.
3. Check the nozzle is positioned as it was when the reference was set
   (see 2.2) — if you moved the camera or the lens, redo section 2.2.

### 2.2 Calibration and reference — when they must be done

**The camera cannot be used for measurement until both of these are done.**
They are stored and reused for every later run, so you only repeat them when
something in the table below changes.

#### When must I redo them?

| What changed | Calibrate Scale | Set Reference |
|---|---|---|
| Nothing — same rig, next shift | no | no |
| **Camera moved** (position, angle, height) | **YES** | **YES** |
| **Lens changed or refocused** | **YES** | **YES** |
| **Working distance changed** (camera↔nozzle) | **YES** | **YES** |
| **Capture ROI changed** (e.g. 320x240 → 320x120) | no | **YES** — see the warning below |
| Nozzle removed and refitted | no | **YES** |
| New PC, same camera and optics | no (copy `settings\`) | no (copy `settings\`) |

> **Anything that changes the optics changes millimetres per pixel.** Moving the
> camera, swapping or refocusing the lens, or changing the distance to the
> nozzle all invalidate the calibration. Measuring with a stale calibration does
> not fail — it silently reports **confidently wrong millimetres**. When in
> doubt, recalibrate: it takes under a minute.

#### Do them in this order

Calibration **must** come first. The reference includes a target rectangle sized
in millimetres, so it cannot be built without a scale. If you set the reference
with no calibration stored, you get the lines but **no rectangle and no OK/NG
verdict**.

---

**Step 1 — Calibrate the scale (millimetres per pixel)**

1. Set the **Capture ROI** you intend to use for the test.
2. Place the reference block in view.
3. Type its known size into **Cal. distance (mm)** — default `5`.
4. Press **Auto Calibrate**.
   - If it fails or the result looks wrong, press **Calibrate Scale** instead
     and drag a box around each of the two edges by hand, clicking
     *Detect Edge* for each.
5. **Check the saved `*_scale.bmp`**: the two green lines must sit exactly on
   the block's edges. This is the only check that catches a bad calibration.

> **Auto Calibrate always saves a new calibration**, taking the distance you
> typed as correct. **Measure Block** is the opposite — it measures an unknown
> block using the stored calibration and changes nothing. Calibrate on the known
> reference; measure everything else.

**Step 2 — Set the nozzle reference (spray angle tests)**

This defines the spray axis that the angle is measured against.

1. **Set the Capture ROI you will actually capture at** — see the warning below.
2. **The nozzle must be on the RIGHT-hand side of the frame.** This is fixed in
   the software and cannot be changed from the screen. A nozzle on the left will
   produce wrong angles.
3. Remove the jet from view. The nozzle must be **dry and still** — no mist, no
   droplets.
4. Press **Set Reference**. A still is captured and the dialog opens.
5. **Drag along the nozzle tip edge** to draw the red line. Auto-detection is
   unreliable on the reflective nozzle, so you place this line yourself — it is
   the single most important input to the spray angle.
6. The app builds the rest automatically:
   - the **blue centre line** through the tip midpoint, perpendicular to your
     red line — this is the spray axis
   - a **red target rectangle** on that axis, used for the OK/NG verdict
7. **Check the saved overlay image before closing.** If the red line is not on
   the tip edge, every angle from now on is measured against the wrong axis.

> **The reference only applies to frames of the same size it was set at.**
> If you set the reference at `320x240` and then capture at `320x120`, the app
> **silently ignores it**: the angle falls back to edge-to-edge instead of
> deviation from the spray axis, and the `in_rect` column comes out empty.
> Nothing warns you. **Set the reference at the ROI you will capture at**, and
> redo it whenever you change the ROI.

> **Changing the ROI does not spoil the calibration.** Millimetres per pixel is
> a property of the lens, not of how many sensor rows you read. You may see a
> note that the calibration was made on a different frame size — that is telling
> you the magnification is assumed unchanged, which is correct for a simple ROI
> crop. Only redo the calibration if the **optics** changed.

**Step 3 — Confirm it took**

Run one capture and open the measure folder. You should see:

- green edge lines sitting on the visible jet edges
- an `in_rect` column in the CSV reading `OK` or `NG` (not blank)
- results in **millimetres**, not pixels

If any of those is missing, go back to the matching step above.

---

## 3. The screen

The window has the live preview on the right, and on the left, from top to
bottom: **Capture Settings**, then three button groups.

### 3.1 Capture Settings

| Field | Default | Notes |
|---|---|---|
| Capture time (s) | `4.0` | How long the burst records |
| Camera index | `1` | Leave at 1 unless you have more than one camera |
| Exposure (µs) | `500` | See the warning below |
| Capture ROI | `320x240` | `320x240` → **1048 fps**; `320x120` → **1798 fps** |
| Run label (optional) | empty | Free text, e.g. `IN39-30U` — added to every folder and file name |
| Output base folder | app folder | Where `captures`, `injection images` and `measure` are written |

> **Exposure does not change the frame rate.** The rate is set by how many
> sensor **rows** are read, not by exposure time. 100 µs, 200 µs and 500 µs all
> give the same fps at a given ROI. So keep the exposure **high** for contrast,
> and shorten the **ROI** if you need more speed.

> **Choosing the ROI.** `320x120` is twice as fast and is the right choice for
> the piston stroke and for anything with a fast opening transient. `320x240`
> shows more of the scene. Changing the ROI restarts the preview. **Cropping
> does not change the calibration** — millimetres per pixel is a property of
> the lens, not of how many rows you read.

### 3.2 Initial Setup group

`Calibrate Scale` · `Auto Calibrate` · `Measure Block` · `Measure Angle Block` ·
`Set Reference`

Used in section 2.2. **Measure Block** is the inverse of calibration: it
measures an unknown block using the stored calibration **without** overwriting
it. Calibrate on the known reference, then measure others.

### 3.3 Workflow group

Checkboxes, then fields, then the manual buttons.

| Checkbox | Default | What it does |
|---|---|---|
| Smart save | off | Detects the injection *while capturing* and writes only those frames. Faster and much smaller, but keeps no full burst |
| Edge detection V2 | off | Alternative edge model. Leave off unless asked |
| Reference on preview | off | Draws the reference lines on the live preview |
| Auto pick frames | off | Ignores *Measure from/to* and picks the steadiest 10 frames itself |
| Ref. lines on output | off | Draws tip line and centre line on saved measure images. The red target rectangle is always drawn |
| Find piston V2 | off | Much faster piston stroke search (~30×). Same result |

| Field | Default | Notes |
|---|---|---|
| Measure from (Nth) / to (Nth) | `10` / `20` | Which frames to measure, counted from the first frame containing a jet |
| Piston FPS (if no meta) | empty | **Fallback only.** Leave blank — Capture Piston records real timestamps |
| Barrel dia (mm) | `6.12` | Injector geometry, used for jet speed and pressure |
| Orifice dia (mm) | `0.155` | As above |

`Find Injection` · `Measure` · `Make Video` · `Find Injection Piston` ·
`Measure Piston` · `Summary`

These run one step at a time on a folder you choose. Normally you do not need
them — the Operation buttons chain everything automatically. Use them to
re-analyse an old run.

### 3.4 Operation group

`Stop Preview` · `Capture` · `Start Monitoring` · `Capture Piston` ·
**`Capture Gel Injection`** · `Open Last Folder`

> Only one of these can own the camera at a time. If a capture is running, the
> others refuse to start and the status bar says so.

---

## 4. Procedures

### 4.1 Spray angle

1. Set **Capture time**, **Exposure**, **ROI** and an optional **Run label**.
2. Press **Capture**. It changes to **Stop Capture** while the burst runs.
3. Fire the injector during the burst.
4. The app then does the rest by itself:
   **find the injection → measure the angle → make a slow-motion video.**
5. Read the result in the **Output** log and press **Open Last Folder**.

**What you get** — in `data\measure\<run>\`:

- Annotated frames with green edge lines
- `<run>_angles.csv` — one row per measured frame
- Mean angle and a confidence level in the log

### 4.2 Piston speed

1. Set the ROI — **`320x120` is recommended**, the stroke needs the frame rate.
2. Check **Barrel dia** and **Orifice dia** match the device under test.
3. Press **Capture Piston** (becomes **Stop Piston**), and fire.
4. Chain: **find the stroke → measure it → make a video.**

**What you get** — in `data\measure\<run>\`:

- `<run>_speed.csv` — per-frame distance and speed, plus a summary block
- `<run>_distance_time.png` and `<run>_speed_time.png`
- In the log: stroke (mm), peak speed, duration, and peak jet speed + pressure

> The video is built from the **measured** frames, so it shows the green line
> tracking the piston edge. **Watch it.** Nearly every bad measurement in this
> pipeline was caught by watching the line, not by reading numbers.

### 4.3 Gel injection

For firing into a gel block.

1. Set ROI and Run label as usual.
2. Press **Capture Gel Injection** (becomes **Stop Gel**), and fire.
3. Chain: **find the injection → make a slow-motion video.** There is **no**
   angle measurement — inside a gel block there is no free jet to measure.

**What you get** — the injection images and `<run>_slowmo.mp4` in
`data\injection images\<run>\`. Nothing is written to `data\measure\`.

> Folders are named `gel_<timestamp>_<ROI>_<label>` so gel runs are easy to find.

> **New feature — check the first few.** The end of a gel injection is detected
> differently from a jet in air (the gel stays deformed, so the scene never
> returns to normal). Confirm the video length looks right for the first runs,
> and report it if the clip is cut short or runs long.

### 4.4 Monitoring (many injections)

1. Press **Start Monitoring**.
2. Fire as many times as you need. Each detected injection is saved and measured
   on its own, one at a time.
3. Press **Stop Monitoring** when finished.

> No videos are made in monitoring mode. Drips and mist are detected and
> discarded automatically — they are logged but not saved.

### 4.5 Comparing several runs

1. Press **Summary**.
2. Select the measured run folders (multi-select).
3. A `summary_<timestamp>.csv` is written to the top of `data\measure\`.

It reports, for stroke, peak speed, duration, jet speed and pressure:
n, mean, standard deviation, **CV %**, min, median, max.

> **CV % is the number that answers "is this injector repeatable?"** — which is
> usually why the batch was run. Any folder that had to be skipped is listed
> **with the reason**, so you always know how many runs were actually averaged.

---

## 5. Reading the results

### 5.1 Where files go

All output sits under the **Output base folder**:

| Folder | Contents |
|---|---|
| `captures\` | The raw burst, one folder per run |
| `injection images\` | Just the injection, plus the slow-motion video |
| `measure\` | Annotated frames, CSV reports and plots |
| `settings\` | Your calibration and nozzle reference |
| `app.log` | Every message the app has printed |

Run folders are named `<timestamp>_<ROI>_<label>`, prefixed `piston_`, `gel_` or
`monitor_` by job. Reports are named after their folder, so a file stays
identifiable after being copied out.

### 5.2 Spray angle — `<run>_angles.csv`

| Column | Meaning |
|---|---|
| `angle_deg` | The reported angle for that frame |
| `quality` / `confidence` | 0–100 score and **High / Medium / Low** |
| `in_rect` | **OK** or **NG** — did the jet stay inside the target rectangle |
| `coverage`, `rms_*_px` | How well the fitted line matched the visible edge |

Frames scoring **Low** are excluded from the trusted mean. A run with many Low
frames usually means the jet had already decayed — capture earlier, or use
**Auto pick frames**.

### 5.3 Piston speed — `<run>_speed.csv`

| Column | Meaning |
|---|---|
| `time_ms` | Real elapsed time from the camera's own timestamps |
| `distance_mm` | Travel from the resting position |
| `speed_mm_s`, `speed_m_s` | Piston speed |
| `stable` | `no` = the detector may have jumped to a different edge on that frame |

> Frames marked `stable = no` are **reported, never removed**. Peak speed is
> simply the largest value in the speed column, so the summary and the plotted
> curve always show the same number.

---

## 6. If something goes wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| "No injection detected" | The burst missed the shot, or motion was too small | Fire during the burst; increase capture time |
| Results in pixels, no millimetres | No calibration stored | Do section 2.2 step 1 |
| Angle looks wrong / no `in_rect` | No nozzle reference stored | Do section 2.2 step 2 |
| `in_rect` blank, angle looks like edge-to-edge | Reference was set at a **different ROI** than you captured at | Redo **Set Reference** at the ROI you are using (2.2 step 2) |
| Millimetres look wrong but nothing failed | Stale calibration — camera, lens or distance changed | Redo **Auto Calibrate** (2.2 step 1) |
| Angles wrong on every frame | Nozzle is on the **left** of the frame | Re-aim so the nozzle is on the **right** |
| Green line not on the piston edge | Lighting | The piston must be a **dark shape on a bright barrel**. Adjust the light and re-run |
| A button does nothing | Another job owns the camera | Read the status bar; stop the running capture first |
| Frame rate lower than expected | ROI, not exposure | Switch to `320x120`. Raising exposure will not cost you frame rate |
| Preview stopped by itself | Camera disconnected | Reconnect, then press **Stop Preview** / start again |

**Before asking for help**, collect:

1. `app.log` from the output folder
2. The run folder from `captures\` (or `injection images\`)
3. What you expected versus what you got

---

## 7. Quick reference

```
FIRST TIME          Auto Calibrate  →  Set Reference   (in that order)
REDO BOTH IF        camera moved / lens changed / refocused / distance changed
REDO REFERENCE IF   Capture ROI changed, or nozzle refitted
ALWAYS              nozzle on the RIGHT of the frame

SPRAY ANGLE         Capture              → angle + video
PISTON SPEED        Capture Piston       → speed curves + video
GEL INJECTION       Capture Gel Injection→ images + video
REPEATABILITY       Start Monitoring ... Stop Monitoring
COMPARE RUNS        Summary              → CV %

ROI  320x240 = 1048 fps      320x120 = 1798 fps
Exposure does NOT change the frame rate. The ROI does.
```
