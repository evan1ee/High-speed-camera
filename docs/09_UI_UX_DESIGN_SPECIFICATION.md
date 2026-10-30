# UI/UX Design Specification: C++20 / Qt 6 Modern Desktop Interface

This document specifies the user interface (UI) and user experience (UX) architecture for the refactored needle-free injector test toolkit. It replaces the legacy single-window scrolling form of the Python/Tkinter app with a modern, decoupled, professional industrial instrument interface.

---

## 1. Design Vision & Core Principles

### 1.1 The "Three Primary Functions" Model
The application is organized around the **three primary test workflows** of the test rig:
1. 🎯 **Spray Angle Test**: High-speed capture in air $\to$ sub-pixel edge detection $\to$ spray cone divergence $\to$ nozzle axis deviation $\to$ target rectangle pass/fail verdict.
2. ⚡ **Piston Speed Measure**: Ampoule barrel tracking $\to$ sub-pixel edge detection with common slope $\to$ displacement curve $\to$ Savitzky-Golay derivative $\to$ exit velocity & impact pressure.
3. 🧊 **Capture Gel Injection**: Penetration burst into ballistic gelatin $\to$ temporal motion end rule $\to$ slow-motion playback video.

### 1.2 Separation of Concerns
- **Operational Workspace (Clean & Focused)**: When conducting tests, operators only see the live camera, essential test controls, and immediate measurement results.
- **Top Quick-Parameter Bar**: Only frequently adjusted parameters (ROI Preset, Exposure, Duration, Run Label) sit in a slim, non-intrusive top bar.
- **Dedicated Settings Page**: Deep hardware configurations (USB/camera index, folder paths, injector geometry defaults, and algorithm tuning thresholds) are completely isolated in a dedicated **Settings** page accessible via the navigation bar.
- **Dedicated Calibration & Metrology Page**: Scale calibration, nozzle reference line drawing, and angle block verification are isolated into a guided setup workspace.
- **Split Viewport**: The live camera stream is permanently visible on the right, while the left workspace dynamically hosts the active test controls and latest test results.

---

## 2. Global Layout Architecture: Split Viewport

```
+-------------------------------------------------------------------------------------------------------------+
| TOP PARAMETER BAR (Quick Adjustments)                                                                       |
| [ROI: 320x240 (~1048 fps) v]  [Exp: 500 us]  [Dur: 4.0 s]  [Label: ____________]  [Out: D:/data/captures/ ]  |
| Status Pills:  [Scale: 0.0523 mm/px (OK)]   [Nozzle Ref: 320x240 (OK)]   [Camera: AH7040MU000 Online]        |
+---+----------------------------------------------------+----------------------------------------------------+
| N | LEFT WORKSPACE (Task-Focused Operation & Results)  | RIGHT WORKSPACE (Pinned Live Camera Viewport)      |
| A |                                                    |                                                    |
| V | [Spray Angle Test Workspace]                       | +------------------------------------------------+ |
|   | (Switches dynamically per Nav Item:                | |                                                | |
| B |  - Spray Angle View                                | |           High-Speed Camera Live Stream        | |
| A |  - Piston Speed View                               | |            (Hardware-Accelerated QOpenGL)      | |
| R |  - Gel Capture View                                | |                                                | |
|   |  - Calibration & Setup View                        | |   Overlay:                                     | |
| 🎯|  - History & Batch Summary View                    | |   - [Yellow Nozzle Tip Line]                   | |
| ⚡|  - Settings View)                                  | |   - [Blue Spray Axis Centerline]               | |
| 🧊|                                                    | |   - [Red Tolerance Target Rectangle]           | |
| 🔄| -------------------------------------------------- | |                                                | |
| 📏| RESULTS INSPECTOR (Appears on completion):         | |                                                | |
| 📊| +-----------------+ +--------------+ +-----------+ | +------------------------------------------------+ |
|---| | Angle: 0.42 deg | | Conf: HIGH88 | | PASS: OK  | | [x1.0] [x2.0] [x4.0] [Fit]  [Grid]  [Target Overlay]|
| ⚙️| +-----------------+ +--------------+ +-----------+ | Frame: 320x240 @ 1048 fps | Dropped: 0 frames    |
|   | Frame Scrubber: [<] [===O========] [>] Frame 14/20 |                                                    |
+---+----------------------------------------------------+----------------------------------------------------+
| PERMANENT ACTION BAR:  [  CAPTURE SPRAY (Space)  ]   [ Stop Preview ]   [ Open Last Folder ]                |
| PIPELINE STEPPER:      [1. Capture (1048 fps)] ===> [2. Extract Window] ===> [3. Measure] ===> [4. Video]   |
+-------------------------------------------------------------------------------------------------------------+
```

---

## 3. Left Navigation Bar (Sidebar)

A sleek, modern vertical navigation bar docked on the far left (width: $64\ \text{px}$ icon-only collapsed, expandable to $180\ \text{px}$ with labels):

| Nav Item | Icon | Label | Shortcut | Primary Purpose |
| :--- | :---: | :--- | :---: | :--- |
| **Workflow 1** | 🎯 | **Spray Angle** | `F1` | Active spray angle testing, Smart save, edge extraction, and cone measurement. |
| **Workflow 2** | ⚡ | **Piston Speed** | `F2` | Piston displacement tracking, velocity derivative, and stagnation impact pressure. |
| **Workflow 3** | 🧊 | **Capture Gel** | `F3` | Ballistic gel penetration recording using temporal end rule. |
| **Workflow 4** | 🔄 | **Monitor** | `F4` | Continuous automated multi-injection monitoring and background event logging. |
| **Setup & Tools**| 📏 | **Calibration** | `F5` | Guided scale calibration ($\text{mm/px}$), nozzle reference setup, angle block test. |
| **Analytics** | 📊 | **History & Batch**| `F6` | Past run inspector, CSV exports, multi-run CV% repeatability summary. |
| **Configuration**| ⚙️ | **Settings** | `F12` | Camera hardware selection, storage defaults, injector geometry, algorithm thresholds. |

---

## 4. Workspaces & Screen Details

### 4.1 View 1: Spray Angle Test Workspace
When **Spray Angle** is selected in the navigation bar:

```
+------------------------------------------------------------------------------+
| 🎯 Spray Angle Test Workspace                                                |
+------------------------------------------------------------------------------+
| WORKFLOW SETTINGS:                                                           |
| [x] Smart Save (RAM detection before write)   [x] Auto pick stable frames    |
| [ ] Edge Detection V2 (erf blurred-step)      [x] Draw reference lines       |
|                                                                              |
| JET MEASUREMENT RANGE:                                                       |
| Measure From (Nth jet frame): [ 10 ]   To (Nth jet frame): [ 20 ]            |
| (Disabled automatically when "Auto pick stable frames" is active)            |
|                                                                              |
| OFFLINE RE-PROCESSING (On Existing Disk Folders):                            |
| [ Find Injection from Burst... ]   [ Measure Angle on Folder... ]            |
| [ Generate Slow-Motion Video... ]                                            |
+------------------------------------------------------------------------------+
| RESULTS INSPECTOR (Auto-populated upon capture completion):                  |
| +-------------------------+ +-------------------------+ +------------------+ |
| | Angle: 0.42°            | | Confidence: HIGH (88)   | | Target: PASS (OK)| |
| | Worst Edge Deviation    | | Fit: 92 | Cov: 99 | Span| | In Tolerance Rect| |
| +-------------------------+ +-------------------------+ +------------------+ |
|                                                                              |
| Annotated Frame Inspection:                                                  |
| [<] Step Back   [ Frame 14 of 20 (frame_000042.bmp) ]   Step Forward [>]     |
| [===========================O==============================================] |
| [x] Show Subpixel Edges   [x] Show Fitted Lines   [x] Show Target Rectangle  |
+------------------------------------------------------------------------------+
```

### 4.2 View 2: Piston Speed Measure Workspace
When **Piston Speed** is selected:

```
+------------------------------------------------------------------------------+
| ⚡ Piston Speed & Travel Workspace                                           |
+------------------------------------------------------------------------------+
| INJECTOR SPECIFICATIONS (Device Under Test):                                 |
| Barrel Diameter:   [  6.12 mm ]      Orifice Diameter: [ 0.155 mm ]          |
| Area Ratio:        1560.8x           Fluid Density:    [ 1000.0 kg/m³ ]      |
|                                                                              |
| DETECTION OPTIONS:                                                           |
| [x] Find Piston V2 (Fast coarse-to-fine multi-threaded scan)                 |
| [x] Lock Face Slope (Pooled common rigid-body angle across stroke)           |
|                                                                              |
| OFFLINE RE-PROCESSING:                                                       |
| [ Re-Detect Stroke Window... ]    [ Re-Measure Speed & Plot... ]             |
+------------------------------------------------------------------------------+
| RESULTS INSPECTOR:                                                           |
| +-------------------+ +-------------------+ +------------------------------+ |
| | Stroke: 12.45 mm  | | Piston: 165.2 mm/s| | Jet Exit: 257.8 m/s          | |
| | Duration: 142.3 ms| | Peak Speed (SG)   | | Pressure: 33.2 MPa (Peak)    | |
| +-------------------+ +-------------------+ +------------------------------+ |
|                                                                              |
| EMBEDDED CURVE TABS:                                                         |
| [ Displacement (mm) ]  [ Speed (mm/s) ]  [ Jet Velocity ]  [ Impact Pressure]|
| +--------------------------------------------------------------------------+ |
| |  [Interactive Plot: Zoom / Pan / Hover Readout / Save PNG / Copy]        | |
| |    200 |                                 .-.                             | |
| |    150 |                                /   \                            | |
| |    100 |                               /     \                           | |
| |     50 |                              /       \__________                | |
| |      0 +-----------------------------'-----------------------            | |
| |        0           50          100         150         200 ms            | |
| +--------------------------------------------------------------------------+ |
+------------------------------------------------------------------------------+
```

### 4.3 View 3: Capture Gel Injection Workspace
When **Capture Gel** is selected:

```
+------------------------------------------------------------------------------+
| 🧊 Gel Injection Capture Workspace                                           |
+------------------------------------------------------------------------------+
| GEL PENETRATION RECORDING:                                                   |
| End Detection Policy: TEMPORAL MOTION DECAY (Fixed)                          |
| (Presence background trough is disabled because gelatin stays permanently    |
| deformed and dyed after injection).                                          |
|                                                                              |
| Smart Save: FORCED OFF (Burst saved completely to preserve full event).      |
| Angle Measurement: BYPASSED (No free spray cone exists in a solid gel block).|
+------------------------------------------------------------------------------+
| POST-CAPTURE INSPECTION:                                                     |
| [ Video Playback Tab ]   [ Extracted Frame Sequence ]                        |
| +--------------------------------------------------------------------------+ |
| |                                                                          | |
| |           [ Embedded Slow-Motion MP4 Player: Play / Pause / 0.25x ]      | |
| |                                                                          | |
| +--------------------------------------------------------------------------+ |
| Extracted Window: Frame 1200 to 1485 (285 frames, 272 ms)                    |
| Folder: data/injection images/gel_2026-08-12-14-30-10_320x240/              |
+------------------------------------------------------------------------------+
```

### 4.4 View 4: Calibration & Metrology Workspace
When **Calibration** is selected:

```
+------------------------------------------------------------------------------+
| 📏 Calibration & Metrology Workspace                                         |
+------------------------------------------------------------------------------+
| STEP 1: SPATIAL SCALE CALIBRATION (mm per pixel)                             |
| Current Scale: 0.052341 mm/px (Saved: 2026-08-12 14:05)  [ Status: VALID ]   |
| Known Gauge Block Thickness: [  5.00 mm ]                                    |
| [ Auto Calibrate (1-Click) ]      [ Manual Calibrate Scale (Draw ROIs)... ]  |
| [ Measure Unknown Block Size (Verification Only) ]                           |
| ---------------------------------------------------------------------------- |
| STEP 2: NOZZLE REFERENCE ALIGNMENT (Spray Axis & Target Window)              |
| Current Reference: 320x240 Frame Size                    [ Status: MATCHED ] |
| Centerline Angle: 0.00° (Horizontal)   Target Rect: 1.00..6.51 mm            |
| [ Set Nozzle Reference (Draw Tip Line)... ]                                  |
| ---------------------------------------------------------------------------- |
| STEP 3: METROLOGY BENCHMARK                                                  |
| Precision Machined Angle Block:                                              |
| [ Measure Angle Block (Single Still Verification) ]                          |
+------------------------------------------------------------------------------+
```

### 4.5 View 5: Settings Workspace (Deep Configuration)
When **Settings** is selected in the navigation bar:

```
+------------------------------------------------------------------------------+
| ⚙️ Application & Hardware Settings                                           |
+------------------------------------------------------------------------------+
| CAMERA HARDWARE & INTERFACE:                                                 |
| Device:          [ Huaray AH7040MU000 (Serial: 22A0142)                   v] |
| Interface:       USB 3.0 Vision (GenTL Producer: MVProducerU3V.cti)          |
| Packet Timeout:  [ 500 ms ]               Camera Free-Run: [x] Enabled       |
| ---------------------------------------------------------------------------- |
| STORAGE & FILE ORGANIZATION:                                                 |
| Base Data Folder: [ D:/01_Data/code/spray-angle-test/data/       ] [Browse]  |
| Subfolders:       captures/  |  injection images/  |  measure/               |
| Run Folder Format: YYYY-MM-DD-HH-MM-SS_<aspect>[_<label>]                    |
| Keep Raw Bursts:  [x] Yes (Untick to auto-delete raw bursts if Smart Save OK)|
| ---------------------------------------------------------------------------- |
| DEFAULT INJECTOR GEOMETRY:                                                   |
| Default Barrel Diameter:  [ 6.12 mm ]     Default Orifice: [ 0.155 mm ]      |
| Default Fluid Density:    [ 1000 kg/m³ ]                                     |
| ---------------------------------------------------------------------------- |
| COMPUTER VISION & ALGORITHM THRESHOLDS (Advanced):                           |
| Temporal Motion Diff Threshold: [ 25 ]      Min Injection Peak: [ 300 px ]   |
| End Residual Multiplier:        [ 1.8 ]     RANSAC Inlier Tol:  [ 2.5 px ]   |
| Piston Dark Body Fraction:      [ 0.08 ]    Piston Min Body Run:[ 30 px ]    |
| [ Restore Defaults ]                                            [ Save & Apply]|
+------------------------------------------------------------------------------+
```

---

## 5. Viewport: Pinned Live Camera Stream

The right-hand side of the main window is dedicated to the live camera view:
- **Zero-Lag OpenGL Canvas**: Implemented using `QOpenGLWidget` inside `QGraphicsView`, rendering 8-bit grayscale textures at native GPU speed.
- **Always Active During Alignment**: When switching between Spray Angle, Piston Speed, and Gel tabs, the camera never resets or flickers.
- **Snapped Reference Overlays**:
  - Yellow user-set nozzle tip line.
  - Blue perpendicular spray axis.
  - Red dashed tolerance target rectangle ($1.00\dots6.51\ \text{mm}$ downstream).
  - Can be toggled on/off instantly via an overlay eye icon.
- **Interactive Tools**:
  - Zoom levels: `100%`, `200%`, `400%`, `Fit to Window` (or smooth mouse wheel zoom).
  - Crosshair alignment guide with real-time coordinate and grayscale pixel intensity readout: `X: 184  Y: 120  Val: 242 (95%)`.

---

## 6. Permanent Action Bar & Visual Pipeline Stepper

Permanently anchored along the bottom of the window:

```
+----------------------------------------------------------------------------------------------------+
| [  CAPTURE SPRAY (Spacebar)  ]   [ Stop Preview ]   [ Open Last Folder ]   [ Clear Output ]        |
|----------------------------------------------------------------------------------------------------|
| PIPELINE STATUS:                                                                                   |
| (O) 1. Burst Capture ==> (O) 2. Extract Window ==> (O) 3. Measure Angle ==> (O) 4. Make Video      |
| Progress: [================================== 100% ===================================] (1.82 s)   |
+----------------------------------------------------------------------------------------------------+
```

### 6.1 Dynamic Action Button
The primary button dynamically updates its text and color based on the selected Nav tab:
- On **Spray Angle Tab**: Large blue button: `[ CAPTURE SPRAY (Spacebar) ]` $\to$ toggles to red `[ STOP CAPTURE ]` during acquisition.
- On **Piston Speed Tab**: Large blue button: `[ CAPTURE PISTON (Spacebar) ]` $\to$ toggles to red `[ STOP PISTON ]`.
- On **Gel Injection Tab**: Large blue button: `[ CAPTURE GEL (Spacebar) ]` $\to$ toggles to red `[ STOP GEL ]`.
- On **Continuous Monitor Tab**: Toggle button: `[ START MONITORING ]` $\to$ toggles to `[ STOP MONITORING ]`.

### 6.2 Visual Pipeline Stepper
During chained workflows, each node highlights in real time:
- `Active`: Animated pulsing blue node.
- `Success`: Green checkmark node with elapsed time.
- `Error`: Red error node with tooltip explanation.

---

## 7. Interactive Setup Dialogs

### 7.1 Zoomable Scale Calibration Dialog (`CalibrationDialog`)
- Replaces the fixed-size Tkinter canvas.
- Allows zooming up to $800\%$ directly onto the gauge block edge.
- User drags a box (ROI) around the upper edge, and a box around the lower edge.
- Live detection: Sub-pixel green lines snap immediately inside the ROIs upon release.
- Real-time readout: `Distance: 95.53 px -> Scale: 0.05234 mm/px`.

### 7.2 Zoomable Nozzle Reference Dialog (`ReferenceDialog`)
- High-magnification still image of the dry nozzle tip.
- User clicks and drags directly along the vertical nozzle face to draw the **yellow tip line**.
- The system live-renders:
  - The blue spray axis perpendicular to the tip.
  - The calibrated red target rectangle downstream of the nozzle.
- Live check: Immediate visual confirmation before closing the dialog.

---

## 8. Alignment with Decoupled Architecture

This UI design directly supports the **decoupled vertical-slice architecture** specified in `docs/08_CPP_QT6_MIGRATION_PLAN.md`:

1. **Independent Page Widgets**: Each workspace (Spray Angle, Piston Speed, Gel, Calibration, Summary, Settings) is an isolated C++ class inheriting from `QWidget` and registered via `IFeatureModule`.
2. **Dynamic Navigation Populating**: The left navigation sidebar queries the `FeatureRegistry`. If a module is disabled in CMake (`-DHSC_ENABLE_GEL=OFF`), its icon never appears in the sidebar, and no empty tabs or broken controls are left behind.
3. **Clean App Settings**: Removing settings from the main window and centralizing them in `SettingsView` means feature panels only expose operational knobs, keeping the UI uncluttered.
