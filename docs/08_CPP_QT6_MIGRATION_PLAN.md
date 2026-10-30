# C++20 / Qt 6 Migration & UX Redesign Plan

This document is the master engineering plan for migrating the **High-Speed Camera Needle-Free Injector Toolkit** from the current Python/Tkinter implementation (`High speed camera/`) to a unified, native **C++20 / Qt 6** application (building upon `C version/`), achieving **100% functional and numerical parity** while delivering a significantly improved operator User Experience (UX).

---

## 1. Goals & Scope

1. **Full Functional Parity**: Implement all 8 operational and analysis workflows from the Python codebase (Spray Angle, Piston Speed & Hydrodynamics, Gel Injection, Continuous Online Monitoring, Spatial Scale Calibration, Angle Block Verification, Nozzle Reference & Target Rectangle, and Batch Cross-Run Statistical Summary).
2. **Strict Module Decoupling (Plug-and-Play Feature Removal)**: Architect every functional workflow as an isolated **Vertical Feature Slice** with zero cross-feature dependencies. Any feature (e.g., Gel Injection, Piston Speed, Angle Block, Continuous Monitor, or Batch Summary) can be disabled via a single CMake option (`-DHSC_ENABLE_<FEATURE>=OFF`) or by deleting its folder without breaking compilation or modifying the core camera/UI shell.
3. **Exact Numerical Parity**: Match Python measurement outputs on synthetic ground-truth tests and real rig bursts ($\pm 0.01^\circ$ for spray angles, $\pm 0.05\ \text{px}$ for piston tracking, identical `OK`/`NG` verdicts, and identical CSV/JSON schemas).
4. **Superior Operator UX**: Eliminate the usability bottlenecks of the Tkinter layout (scrolling button columns, silent resolution mismatches, external folder switching to view results) with a task-oriented Qt 6 interface that dynamically adapts to whichever feature modules are enabled.
5. **Zero-Copy Native Performance**: Keep the camera open across preview and capture, process burst buffers directly in RAM with OpenMP/AVX2, and deploy as a self-contained native Windows folder (`~25 MB`, instant startup).

---

## 2. UX Redesign Specification ("Better UX")

### 2.1 Pain Points in the Current Python Tkinter GUI

| Pain Point in Current Tkinter UI (`hsc/gui/layout.py`) | Impact on Rig Operator | Qt 6 UX Solution |
| :--- | :--- | :--- |
| **Single Scrolling Left Column**: 17 buttons, 6 checkboxes, and 10 text fields stacked vertically. | On laptop/rig monitors, the primary **Operation** buttons (`Capture`, `Capture Piston`) scroll off the bottom of the screen. | **Task-Oriented Mode Tabs + Fixed Action Bar**: Primary capture controls are permanently docked at the bottom-left and never scroll out of view. |
| **Silent Reference Resolution Mismatch**: Reference set at `320x240` is silently ignored when capturing at `320x120`. | Angle silently reverts from axis-deviation to cone-angle, and `in_rect` comes out blank without warning. | **Live Calibration & Reference Status Pills**: Header bar shows persistent green/amber/red status badges (`Scale: 0.052 mm/px [OK]`, `Ref: 320x240 [MISMATCH!]`) with one-click fix. |
| **No In-App Result Viewing**: Operator must click `Open Last Folder` and open `.bmp`, `.png`, and `.csv` files in external Windows apps. | Slows down every shot; operator has to alt-tab between Explorer, photo viewer, and Excel. | **Integrated Results Inspector Tab**: Displays KPI cards (`Angle`, `Confidence`, `OK/NG` banner, `Peak Speed`, `Pressure`), an interactive frame scrubber for annotated images, and embedded curve plots right inside the main window. |
| **Text-Only Pipeline Feedback**: Chained stages (`Capture -> Extract -> Measure -> Video`) only print lines to a text box. | Hard to tell at a glance which stage is running or how many frames were dropped. | **Visual Pipeline Stepper & Progress Bar**: 4-stage visual progress indicator with live FPS and dropped-frame badge. |
| **Separate Modal Popups for Every Setup Step**: Basic Tkinter canvases for ROI and Reference line drawing lack zoom/pan. | Hard to place sub-pixel nozzle tip lines on a small `320x240` image. | **Zoomable `QGraphicsView` Canvas**: Smooth mouse-wheel zoom (up to $800\%$), pan, pixel coordinate/brightness readout, and live snapped geometry overlays. |

---

### 2.2 New Qt 6 Main Window Wireframe

```
+--------------------------------------------------------------------------------------------------+
| [Camera: AH7040MU000 Connected]  [ROI: 320x240 (~1048 fps) v]  [Exp: 500 us]  [Dur: 4.0 s]       |
| [Scale: 0.0523 mm/px (OK)]       [Nozzle Ref: 320x240 (OK)]    [Run Label: ________] [Out: ...]  |
+----------------------------------------+---------------------------------------------------------+
| WORKFLOW MODE TABS                     | VIEWPORT: [ Live Preview ]  [ Results Inspector ]       |
| +------------------------------------+ | +-----------------------------------------------------+ |
| | [1. Spray] [2. Piston] [3. Gel]    | | |  KPI BANNER (in Results Inspector):                 | |
| | [4. Monitor] [5. Setup] [6. Batch] | | |  +---------------+ +---------------+ +-----------+  | |
| +------------------------------------+ | |  | Angle: 0.42°  | | Conf: HIGH 88 | |  PASS: OK |  | |
| |                                    | | |  +---------------+ +---------------+ +-----------+  | |
| | (Active Tab: 1. Spray Angle)       | | +-----------------------------------------------------+ |
| |                                    | | |                                                     | |
| |  [x] Smart save (RAM detect)       | | |                                                     | |
| |  [x] Auto pick stable frames       | | |           Interactive QGraphicsView                 | |
| |  [ ] Edge detection V2 (erf)       | | |     (Live Camera Stream OR Annotated Frame /        | |
| |  [x] Show reference on preview     | | |      Piston Speed & Pressure Curves)                | |
| |  [x] Draw ref. lines on output     | | |                                                     | |
| |                                    | | |     [Yellow Tip Line | Blue Axis | Red Target Box]  | |
| |  Measure Jet Frames:               | | |     [Green Fitted Jet / Piston Edge Lines]          | |
| |  From (Nth): [ 10 ]  To: [ 20 ]    | | |                                                     | |
| |                                    | | +-----------------------------------------------------+ |
| |  Offline Re-Run on Folder:         | | | Frame Scrubber: [<] [====O=========] [>]  Frame 14  | |
| |  [Find Injection] [Measure Folder] | | | Zoom: [100%] [200%] [400%] [Fit]   (x=184, y=120)   | |
| |  [Make Slow-Mo Video]              | | +-----------------------------------------------------+ |
| +------------------------------------+ |                                                         |
|                                        | PIPELINE PROGRESS STEPPER                               |
| PERMANENT ACTION BAR (Always Visible)  | [1. Capture] ==> [2. Extract] ==> [3. Measure] ==> [4. Video]
| +------------------------------------+ | [=================== 100% (1.82s) ===================]  |
| | [  CAPTURE SPRAY (Space)  ]        | | +-----------------------------------------------------+ |
| | [Stop Preview]   [Open Last Folder]| | | Output Log (collapsible, mirrored to data/app.log)  | |
| +------------------------------------+ | +-----------------------------------------------------+ |
+----------------------------------------+---------------------------------------------------------+
```

---

### 2.3 Mode Tabs Breakdown

1. **Tab 1 — Spray Angle**:
   - Checkboxes: `Smart save`, `Auto pick frames`, `Edge detection V2`, `Reference on preview`, `Ref. lines on output`.
   - Spinboxes: `Measure from (Nth)` (`10`), `Measure to (Nth)` (`20`) — automatically disabled when `Auto pick frames` is checked.
   - Offline buttons: `Find Injection...`, `Measure Folder...`, `Make Video...`.
   - Primary Action Button: **Capture Spray** (toggles to **Stop Capture** during burst).

2. **Tab 2 — Piston Speed**:
   - Checkbox: `Find piston V2 (fast coarse-to-fine scan)` (default ON).
   - Injector Geometry fields: `Barrel diameter (mm)` (`6.12`), `Orifice diameter (mm)` (`0.155`), `Fallback FPS` (`1048`).
   - Offline buttons: `Find Piston Stroke...`, `Measure Piston Folder...`, `Make Video...`.
   - Primary Action Button: **Capture Piston** (toggles to **Stop Piston** during burst).

3. **Tab 3 — Gel Injection**:
   - Info banner explaining `end_rule="temporal"` and Smart Save forced off.
   - Offline buttons: `Extract Gel Event...`, `Make Video...`.
   - Primary Action Button: **Capture Gel Injection** (toggles to **Stop Gel**).

4. **Tab 4 — Continuous Monitor**:
   - Live counters: `Frames Fed`, `Events Detected`, `Drips Discarded`, `State: ARMED / RECORDING / PADDING`.
   - Live Event Table: Rows added in real time as shots fire (`Event #`, `Folder`, `Peak Pixels`, `Measured Angle`, `Confidence`, `In-Rect Verdict`), clicking any row loads its frames into the Results Inspector.
   - Primary Action Button: **Start Monitoring** (toggles to **Stop Monitoring**).

5. **Tab 5 — Setup (Calibration & Reference)**:
   - **Step 1: Spatial Scale (`mm/px`)**:
     - Input: `Cal. distance (mm)` (`5.0`).
     - Buttons: `Auto Calibrate` (1-click), `Manual Calibrate Scale...` (opens zoomable ROI dialog), `Measure Unknown Block` (read-only verification).
   - **Step 2: Nozzle Reference & Angle Block**:
     - Buttons: `Set Nozzle Reference...` (opens zoomable tip-line drawing dialog), `Measure Angle Block` (single-still verification).

6. **Tab 6 — Batch Summary**:
   - Embedded multi-run folder checklist (newest first, filtering folders containing `*_speed.csv`) + `Select All` / `Clear` / `Browse External...`.
   - Live statistical table showing per-run values and summary rows (`n`, `mean`, `std`, **`cv_percent`**, `min`, `median`, `max`) for `stroke_mm`, `peak_speed_mm_s`, `duration_ms`, `peak_jet_speed_m_s`, `peak_jet_pressure_MPa`.
   - Button: `Export Summary CSV`.

---

## 3. Open-Closed Plugin Architecture (Easy Feature Removal & Zero-Touch Extension)

In the legacy Python codebase, features were coupled in five places:
1. `layout.py` hardcoded all 17 buttons and 6 checkboxes.
2. `camera_worker.py` hardcoded separate `_do_capture`, `_do_piston_capture`, and `_do_monitor` methods plus a static `MONITOR_DISABLED_BUTTONS` tuple.
3. Chaining relied on ad-hoc boolean flags (`_auto_chain`, `_piston_chain`, `_gel_chain`, `_monitor_chain`) scattered across 5 mixins.
4. `monitor.py` directly depended on `measure_angle.py`'s GUI handler (`_on_extract_done`).
5. Result formatting was hardcoded per feature.

To satisfy the **Open-Closed Principle (OCP)** — *"open for extension of new features, closed for modification of existing core/shell code, and trivial to remove any feature"* — the C++20 / Qt 6 architecture is built around **Six Architectural Pillars**:

---

### 3.1 Pillar 1: Generic Camera Service (Zero Workflow Logic in Camera Layer)
`hsc_camera` (`CameraService`) provides **only** generic hardware primitives and knows nothing about spray jets, pistons, gel blocks, or monitor state machines:
- `startPreview()` / `stopPreview()` — streams `RawFrame` to preview subscribers.
- `grabStill()` — captures a single `RawFrame` for any caller.
- `grabBurst(BurstConfig)` — captures $N$ seconds of `RawFrame` into a contiguous `BurstBuffer` in RAM (always recording per-frame `blockId` and `timeStamp`, which costs only 16 bytes/frame) and returns the `BurstBuffer` to whichever feature module requested the burst.
- `startStream(FrameConsumerCallback)` — feeds live `RawFrame` objects to an abstract consumer callback while keeping the preview active.
- `CameraLockGuard` — RAII token ensuring only one feature can run an active capture/stream at a time; the UI shell disables other camera-requesting actions generically via this token rather than hardcoding button lists.

---

### 3.2 Pillar 2: Shared POD Data Stores Live in Foundation, Never in Feature Modules
Features never `#include` headers from other features. When `spray_angle`, `piston`, or a future feature needs the stored scale (`mm/px`) or nozzle reference (`reference_lines.json`), it reads lightweight Plain-Old-Data (POD) structs located in `hsc_foundation`:
- `ScaleCalibrationStore::load()` $\to$ `std::optional<ScaleCalibration>` (`mm_per_px`, `image_size`).
- `NozzleReferenceStore::load()` $\to$ `std::optional<NozzleReference>` (`red_p0`, `red_p1`, `blue_a`, `blue_b`, `rect`, `image_size`).

**Consequence**: You can completely delete `features/calibration/` or `features/reference/`, and `spray_angle` / `piston` will still compile and run cleanly using existing JSON files (or graceful pixel fallback).

---

### 3.3 Pillar 3: Data-Driven `InspectionReport` Contract (Decoupled Viewport)
If the right-hand `ResultsInspector` hardcoded "Spray Angle cards" and "Piston Speed plots", adding a new feature (e.g., *Gel Penetration Depth* or *Droplet Size Distribution*) would force you to edit `ViewportWidget`.

Instead, `ViewportWidget` renders a generic, data-driven **`InspectionReport`** struct published by any feature:

```cpp
// include/hsc/shell/inspection_report.h
enum class BadgeStatus { Neutral, PassGreen, WarnAmber, FailRed };

struct KpiCard {
    QString label;        // e.g. "Spray Angle", "Peak Speed", "Penetration Depth"
    QString value;        // e.g. "0.42 deg", "165.2 mm/s", "8.4 mm"
    QString subtext;      // e.g. "Trusted Mean (10 frames)"
    BadgeStatus status = BadgeStatus::Neutral;
};

struct PlotAttachment {
    QString title;        // e.g. "Distance vs Time", "Speed vs Time", "Droplet Histogram"
    QString imagePath;    // Rendered PNG chart path
};

struct InspectionReport {
    QString featureId;                  // e.g. "spray_angle", "piston", "gel_penetration"
    QString runTitle;                   // e.g. "2026-08-12-14-07-22_320x240"
    QString outputFolder;               // Target for "Open Last Folder"
    QString csvPath;                    // Optional CSV table to preview in-app
    QString videoPath;                  // Optional slowmo.mp4 path
    std::vector<KpiCard> kpis;          // Dynamically rendered as top KPI banner cards
    std::vector<QString> framePaths;    // Dynamically populates the interactive Frame Scrubber
    std::vector<PlotAttachment> plots;  // Dynamically adds sub-tabs for each curve/plot
};
```

**Consequence**: Any new feature can display custom KPI badges, interactive frame sequences, and custom plots without modifying a single line of `ViewportWidget`.

---

### 3.4 Pillar 4: Composable `PipelineChain` Runner (Decoupled Workflow Chaining)
Instead of boolean flags (`_auto_chain`, `_piston_chain`, `_gel_chain`), `AppServices` provides a declarative, multi-step background pipeline runner:

```cpp
// include/hsc/shell/pipeline_runner.h
struct PipelineContext {
    BurstBuffer burst;
    std::filesystem::path burstDir;
    std::filesystem::path extractDir;
    std::filesystem::path measureDir;
    nlohmann::json scratchMeta;
    std::optional<InspectionReport> finalReport;
};

struct PipelineStep {
    QString label; // Displayed automatically in the UI Pipeline Progress Stepper!
    bool runsOnCameraThread = false;
    std::function<void(PipelineContext&, ProgressReporter&)> run;
};
```

Each feature composes its own pipeline chain at runtime:
- **Spray Angle**: `[ {"1. Capture", ...}, {"2. Extract", ...}, {"3. Measure Angle", ...}, {"4. Make Video", ...} ]`
- **Piston Speed**: `[ {"1. Capture Piston", ...}, {"2. Track Stroke", ...}, {"3. Measure Speed", ...}, {"4. Make Video", ...} ]`
- **Gel Injection**: `[ {"1. Capture Gel", ...}, {"2. Extract Temporal", ...}, {"3. Make Video", ...} ]`
- **Any Future Feature**: Can submit a 1-step, 2-step, or 6-step chain; the bottom **Pipeline Progress Stepper** automatically adapts its step nodes to match `chain.size()`.

---

### 3.5 Pillar 5: Service Broker (`AppServices`) for Loose Inter-Feature Hooks
Sometimes one feature optionally delegates to another if present (e.g., **Continuous Monitor** saves an injection event folder and wants to auto-measure it with **Spray Angle** if the Spray Angle module is compiled in).
Rather than `features/monitor/` `#include`-ing `features/spray_angle/`, `AppServices` provides an optional **Folder Analyzer Registry**:

```cpp
// include/hsc/shell/app_services.h
using FolderAnalyzerFn = std::function<InspectionReport(
    const std::filesystem::path& folder, ProgressReporter& progress)>;

class AppServices {
public:
    CameraService& camera();
    PipelineRunner& pipeline();
    void publishReport(const InspectionReport& report);
    void log(const QString& message);

    // Optional analyzer registry (used by Monitor mode or batch tools):
    void registerFolderAnalyzer(const QString& id, const QString& name, FolderAnalyzerFn fn);
    std::vector<QString> availableAnalyzers() const;
    std::optional<InspectionReport> runAnalyzer(const QString& id, const std::filesystem::path& folder);
};
```
- When `spray_angle` (or `piston`) initializes, it registers `"spray_angle"` (or `"piston"`) as a `FolderAnalyzer`.
- In `monitor`, the user can even pick which registered analyzer to run on each captured event (or `"None — Save Frames Only"` if all measurement modules are disabled!).

---

### 3.6 Pillar 6: Self-Registering Feature Slices (`IFeatureModule` + CMake Auto-Discovery)
Every feature implements `IFeatureModule` and registers itself via a static registration macro:

```cpp
// include/hsc/shell/i_feature_module.h
enum class FeatureCategory { WorkflowTab, SetupTool, BatchTool };

class IFeatureModule {
public:
    virtual ~IFeatureModule() = default;
    virtual QString id() const = 0;                   // e.g. "piston"
    virtual QString title() const = 0;                // e.g. "Piston Speed"
    virtual int displayOrder() const = 0;             // Tab sort order (10, 20, 30...)
    virtual FeatureCategory category() const = 0;     // WorkflowTab, SetupTool, or BatchTool

    virtual void initialize(AppServices& services) {} // Register analyzers / CLI commands
    virtual QWidget* createWidget(AppServices& services, QWidget* parent) = 0;

    // Optional Primary Action Bar binding (when this tab is active):
    virtual QString primaryActionLabel() const { return {}; } // e.g. "Capture Piston"
    virtual QString activeActionLabel() const { return {}; }  // e.g. "Stop Piston"
    virtual bool usesCamera() const { return false; }
    virtual void onPrimaryActionTriggered(AppServices& services) {}

    // Optional live preview QPainter overlay hook:
    virtual void paintPreviewOverlay(QPainter& painter, const QSize& frameSize) const {}
};

#define HSC_REGISTER_FEATURE(ModuleClass) \
    static const bool kRegistered_##ModuleClass = \
        ::hsc::FeatureRegistry::instance().registerModule(std::make_unique<ModuleClass>());
```

In `src/features/CMakeLists.txt`, CMake automatically scans or toggles each feature folder:

```cmake
option(HSC_ENABLE_SPRAY_ANGLE "Enable Spray Angle Measurement module"     ON)
option(HSC_ENABLE_PISTON      "Enable Piston Speed & Tracking module"     ON)
option(HSC_ENABLE_GEL         "Enable Gel Injection Capture module"       ON)
option(HSC_ENABLE_MONITOR     "Enable Continuous Online Monitor module"   ON)
option(HSC_ENABLE_CALIBRATION "Enable Spatial Scale Calibration module"   ON)
option(HSC_ENABLE_REFERENCE   "Enable Nozzle Reference Alignment module"  ON)
option(HSC_ENABLE_ANGLE_BLOCK "Enable Angle Block Verification module"    ON)
option(HSC_ENABLE_SUMMARY     "Enable Cross-Run Batch Summary module"     ON)
```

---

### 3.7 Dependency Graph (Strict One-Way DAG)

```mermaid
graph TD
    subgraph App Shell (Zero Feature Headers Included)
        MAIN[MainWindow + ViewportWidget + PipelineRunner]
        REG[FeatureRegistry + AppServices Broker]
        MAIN <--> REG
    end

    subgraph Pluggable Vertical Feature Slices (Zero Cross-Dependencies)
        F_SPRAY[features/spray_angle]
        F_PISTON[features/piston]
        F_GEL[features/gel]
        F_MON[features/monitor]
        F_CAL[features/calibration]
        F_REF[features/reference]
        F_BLK[features/angle_block]
        F_SUM[features/summary]
        F_NEW[features/future_feature_x]
    end

    subgraph Shared Foundation Layer (Always Present)
        CAM[hsc_camera: Generic Preview / Still / Burst / Stream]
        FOUND[hsc_foundation: BmpIo, Math/TLS/SG, VideoWriter, JSON Stores, TemporalScanner]
    end

    F_SPRAY & F_PISTON & F_GEL & F_MON & F_CAL & F_REF & F_BLK & F_SUM & F_NEW -.->|Self-Registers via HSC_REGISTER_FEATURE| REG
    F_SPRAY & F_PISTON & F_GEL & F_MON & F_CAL & F_REF & F_BLK & F_NEW --> CAM
    F_SPRAY & F_PISTON & F_GEL & F_MON & F_CAL & F_REF & F_BLK & F_SUM & F_NEW --> FOUND
    CAM --> FOUND
```

---

### 3.8 Playbook: How to Remove OR Add Any Feature

#### A. Removing an Existing Feature (1 Step, Zero Code Edits)
| Feature to Remove | CMake Flag to Turn Off | Folder Safe to Delete | Impact on Rest of System |
| :--- | :--- | :--- | :--- |
| **Gel Injection** | `-DHSC_ENABLE_GEL=OFF` | `src/features/gel/` | **Zero impact**. Gel tab disappears; `TemporalScanner` remains in `hsc_foundation`. |
| **Piston Speed & Tracking** | `-DHSC_ENABLE_PISTON=OFF` | `src/features/piston/` | **Zero impact**. Piston tab & curve plotter disappear; Spray Angle & Monitor continue unchanged. |
| **Continuous Monitor** | `-DHSC_ENABLE_MONITOR=OFF` | `src/features/monitor/` | **Zero impact**. Monitor tab and `MonitorEngine`/`EventWriter` are excluded from build. |
| **Batch Summary** | `-DHSC_ENABLE_SUMMARY=OFF` | `src/features/summary/` | **Zero impact**. Batch Summary tab is hidden. |
| **Angle Block Verification** | `-DHSC_ENABLE_ANGLE_BLOCK=OFF` | `src/features/angle_block/` | **Zero impact**. `Measure Angle Block` card disappears from the Setup tab. |
| **Nozzle Reference UI** | `-DHSC_ENABLE_REFERENCE=OFF` | `src/features/reference/` | **Zero impact**. `Set Reference` card disappears; `spray_angle` still reads `reference_lines.json` if present or falls back to cone angle. |
| **Scale Calibration UI** | `-DHSC_ENABLE_CALIBRATION=OFF` | `src/features/calibration/` | **Zero impact**. `Calibrate Scale` card disappears; `piston` still reads `calibration.json` if present or reports px. |
| **Spray Angle** | `-DHSC_ENABLE_SPRAY_ANGLE=OFF` | `src/features/spray_angle/` | **Zero impact** on Piston-only test rigs. App runs as a dedicated Piston Speed workstation. |

#### B. Adding a Brand-New Feature (4 Steps, Zero Edits to `MainWindow` or `CameraService`)
Suppose you want to add a new **"Gel Penetration Depth"** workflow (`features/penetration/`):
1. **Create Folder**: Copy `src/features/_template/` to `src/features/penetration/`.
2. **Write Pure Algorithm (`penetration_tracker.{h,cpp}`)**: Use `hsc_foundation` (`BmpIo`, `ScaleCalibrationStore`, `tls_fit`) to measure penetration depth per frame and write `<run>_penetration.csv`. Add unit tests in `tests/test_penetration.cpp`.
3. **Implement `IFeatureModule` (`penetration_feature.cpp`)**:
   - Return `createWidget()` with your feature's settings controls.
   - In `onPrimaryActionTriggered()`, submit a `PipelineChain` (`GrabBurst -> ExtractTemporal -> TrackPenetration -> MakeVideo`) that ends by calling `services.publishReport(report)` with `KpiCard{"Max Depth", "8.4 mm", PassGreen}` and a depth-vs-time `PlotAttachment`.
   - Add `HSC_REGISTER_FEATURE(PenetrationFeatureModule)` at the bottom of the `.cpp` file.
4. **Add CMake Option**: Add `hsc_add_feature(HSC_ENABLE_PENETRATION penetration)` in `src/features/CMakeLists.txt`.
   - *Result*: The new tab, Primary Action button binding, Pipeline Progress Stepper, Results Inspector KPI cards, Frame Scrubber, and Curve Plot tab all work automatically without touching `MainWindow`, `ViewportWidget`, or `CameraService`!

---

## 4. Target Directory & Module Mapping

```
C version/ (or cpp/)
├── CMakeLists.txt
├── src/
│   ├── foundation/                        # hsc_foundation (Shared primitives, no UI, no SDK)
│   │   ├── app_paths.{h,cpp}              # Paths, safeLabel, makeDestDir, atomic JSON write
│   │   ├── bmp_io.{h,cpp}                 # 8-bit BMP reader/writer with biHeight row-flip
│   │   ├── calibration_store.{h,cpp}      # POD struct + load/save for calibration.json
│   │   ├── reference_store.{h,cpp}        # POD struct + load/save + draw for reference_lines.json
│   │   ├── tls_fit.{h,cpp}                # RANSAC, TLS PCA fit, parabolic vertex, SG filter
│   │   ├── temporal_scanner.{h,cpp}       # OpenMP/AVX2 motion signal + presence/temporal bounds
│   │   └── make_video.{h,cpp}             # slowmo.mp4 synthesis via cv::VideoWriter
│   │
│   ├── camera/                            # hsc_camera (Generic IMV C SDK service)
│   │   ├── raw_frame.h                    # RawFrame (pixels, width, height, blockId, timeStamp)
│   │   └── camera_service.{h,cpp}         # Persistent worker: preview, still, burst, stream
│   │
│   ├── shell/                             # MainWindow shell & pluggable registry (0 feature headers)
│   │   ├── i_feature_module.h             # Abstract plugin interface + HSC_REGISTER_FEATURE macro
│   │   ├── inspection_report.h            # Data-driven KPI cards, frame scrubber & plot attachments
│   │   ├── pipeline_runner.{h,cpp}        # Composable multi-step background chain executor
│   │   ├── app_services.{h,cpp}           # Service broker (camera, pipeline, folder analyzers, log)
│   │   ├── feature_registry.{h,cpp}       # Self-registration singleton for enabled feature slices
│   │   ├── main_window.{h,cpp}            # Top status bar, dynamic tab host, action bar, stepper
│   │   ├── viewport_widget.{h,cpp}        # Zoomable QGraphicsView + generic Results Inspector
│   │   └── main.cpp                       # Entry point
│   │
│   └── features/                          # Self-contained Vertical Feature Slices
│       ├── _template/                     # Copy-paste starter template for adding new features
│       ├── spray_angle/                   # Guarded by HSC_ENABLE_SPRAY_ANGLE
│       │   ├── erf_edge.{h,cpp}           # 4-param LM erf edge estimator
│       │   ├── measure_angle.{h,cpp}      # Headless spray angle pipeline + <run>_angles.csv
│       │   ├── smart_save.{h,cpp}         # RAM detect-before-write planner
│       │   └── spray_feature.{h,cpp}      # Qt tab UI + capture->extract->measure->video chain
│       │
│       ├── piston/                        # Guarded by HSC_ENABLE_PISTON
│       │   ├── piston_track.{h,cpp}       # BarrelProfile, edge modes, common slope, scanPositions
│       │   ├── measure_piston.{h,cpp}     # Timebase inference, SG speed, jet pressure, CSV
│       │   ├── piston_plot.{h,cpp}        # OpenCV XY curve plotter
│       │   └── piston_feature.{h,cpp}     # Qt tab UI + piston capture->track->measure->video chain
│       │
│       ├── gel/                           # Guarded by HSC_ENABLE_GEL
│       │   └── gel_feature.{h,cpp}        # Gel burst -> temporal-end extract -> slowmo video
│       │
│       ├── monitor/                       # Guarded by HSC_ENABLE_MONITOR
│       │   ├── monitor_engine.{h,cpp}     # Online FSM (armed->recording->padding, drip filter)
│       │   ├── event_writer.{h,cpp}       # Async BMP & meta background writer
│       │   └── monitor_feature.{h,cpp}    # Qt tab UI + live event table + sequential measure pump
│       │
│       ├── calibration/                   # Guarded by HSC_ENABLE_CALIBRATION
│       │   ├── calibrate_scale.{h,cpp}    # step/outer ROI edge fit, autoRois, measureBlockSize
│       │   ├── calibration_dialog.{h,cpp} # Interactive zoomable dual-ROI dialog
│       │   └── calibration_feature.{h,cpp}# Setup UI hooks
│       │
│       ├── reference/                     # Guarded by HSC_ENABLE_REFERENCE
│       │   ├── reference_builder.{h,cpp}  # Tip segment -> perpendicular axis + mm target box
│       │   ├── reference_dialog.{h,cpp}   # Interactive zoomable tip-line drawing dialog
│       │   └── reference_feature.{h,cpp}  # Setup UI hooks
│       │
│       ├── angle_block/                   # Guarded by HSC_ENABLE_ANGLE_BLOCK
│       │   ├── measure_block.{h,cpp}      # Single-still angle block fit + block_angles.csv
│       │   └── angle_block_feature.{h,cpp}# Setup UI hook
│       │
│       └── summary/                       # Guarded by HSC_ENABLE_SUMMARY
│           ├── summary_engine.{h,cpp}     # Multi-run CSV reader + n/mean/std/cv%/min/med/max
│           └── summary_feature.{h,cpp}    # Qt tab UI with checklist picker & live stats table
│
└── tests/                                 # GoogleTest suite (compiled per enabled feature)
```

---

## 5. Phased Implementation Plan

### Phase 1: Foundation Layer, Feature Registry & Fast BMP I/O (`hsc_foundation`, `hsc_shell`)
**Objective**: Establish the CMake feature-flag build (`HSC_ENABLE_*`), shared foundation primitives, `IFeatureModule` plugin registry, and orientation-aware BMP I/O.

- [ ] **Task 1.1: CMake Feature Flags & Dependencies Setup**
  - Configure root `CMakeLists.txt` with `hsc_foundation`, `hsc_camera`, `hsc_gui`, `hsc_cli`, and `hsc_tests` targets, plus the 8 `HSC_ENABLE_*` options.
  - Integrate OpenCV C++ (`core`, `imgproc`, `imgcodecs`, `videoio`), `nlohmann/json` (single header), OpenMP, and GoogleTest.
- [ ] **Task 1.2: Paths, JSON Data Stores & Atomic File Persistence (`foundation/`)**
  - Implement `dataRoot()`, `resourceRoot()`, `settingsPath()`, `safeLabel()`, `makeDestDir()`, and atomic JSON save (`temp -> .bak -> replace`).
  - Implement `ScaleCalibrationStore` (`calibration.json`) and `NozzleReferenceStore` (`reference_lines.json`) in `hsc_foundation` so any feature can read them without depending on the Calibration or Reference feature modules.
- [ ] **Task 1.3: Orientation-Aware Raw BMP Reader/Writer (`foundation/bmp_io`)**
  - Implement `readBmpInfo()` and `loadGray()` supporting 8-bit uncompressed BMPs.
  - Handle `biHeight < 0` (IMV SDK top-down) vs `biHeight > 0` (`cv::imwrite` bottom-up) by flipping rows when `bottom_up == true`.
  - **Verification Gate**: Port `tests/test_bmp_orientation.py` and `tests/test_data_root.py` to `hsc_tests` and verify 100% pass.

---

### Phase 2: Mathematical Primitives & Spray Angle Pipeline (`hsc_core`)
**Objective**: Port the complete spray-angle computer vision pipeline and verify against synthetic ground-truth wedges.

- [ ] **Task 2.1: Robust Statistics, Savitzky-Golay & RANSAC $\to$ TLS Line Fitting (`core/tls_fit`)**
  - Implement `robustSigma()` ($1.4826 \times \text{MAD}$), `parabolicVertexOffset()`, and 1D Gaussian smoothing.
  - Implement Savitzky-Golay smoothing and 1st-derivative FIR convolution kernels (`W=21, P=3` for edges; `W=15, P=2` for piston speed).
  - Implement 2-point RANSAC outlier rejection followed by 2x2 PCA covariance Total Least Squares (`tlsFit()`).
- [ ] **Task 2.2: Blurred-Step Error Function (`erf`) Edge Estimator (`core/erf_edge`)**
  - Implement 4-parameter Levenberg-Marquardt solver for $I(y) = \text{base} + \text{amp} \cdot \frac{1}{2}[1 + \operatorname{erf}(\pm \frac{y-\mu}{\sigma\sqrt{2}})]$ over window `peak ± 5` with bounds $\sigma \in [0.3, 5.0]$, $\text{amp} \ge 8.0$.
- [ ] **Task 2.3: Spray Angle Frame & Folder Pipeline (`core/measure_angle`)**
  - Implement `preOnsetBackground()` (from `injection_meta.json`'s `pre_frames >= 8`) with fallback to `computeBackground()` (80-frame temporal median).
  - Implement `extractEdges()` with outward band expansion (`EDGE_BAND_FRAC = 0.15`, `EDGE_BAND_MAX = 12`) and 3 candidate loci (`grad`, `vis` at 0.25, `erf`).
  - Implement `_pickBestLocus()` straightness contest (`EDGE_PICK_TOL = 1.10`), ROI selection (`NOZZLE_SKIP = 14`, `ROI_FRAC = 0.85`), and `findStableWindow()` (`AUTO_PICK_COUNT = 10`, span tol `0.05`, angle tol `0.5°`).
  - Implement nozzle reference centerline projection (`lineAngleDeg`), `resolveAngle` (`max` vs `trusted`), `jetInRect` (`OK`/`NG`), quality scoring (`fit`, `coverage`, `span`, `run_confidence`), `pooled_angle`, 2x supersampled line rendering (`MEASURE_LINE_SS = 2`), and `<run>_angles.csv` generation.
  - **Verification Gate**: Port `tests/test_synthetic_wedges.py`, `tests/test_erf_edge.py`, `tests/test_edge_quality.py`, `tests/test_auto_pick.py`, `tests/test_pooled_fit.py`, `tests/test_pre_onset_bg.py`, and `tests/test_jet_in_rect.py` to GoogleTest. Verify C++ matches `benchmark/baseline.csv` and `Edge V2` scores.

---

### Phase 3: Injection Extraction, Smart Save & Online Monitor Engine (`hsc_core`)
**Objective**: Port offline and online injection event detectors.

- [ ] **Task 3.1: Motion Scanner & Dual-Rule Bounds Detector (`core/injection_extract`)**
  - Embed the OpenMP/AVX2 pixel-diff scanner (`DIFF_THRESH = 25`) directly as an in-memory and on-disk library function.
  - Implement `detectBoundsWithPresence()` supporting both `end_rule = "presence"` (4x downsampled mask, pre-onset median background, 21-frame moving-average trough $\times 1.8$, 25-frame hold) and `end_rule = "temporal"` (for gel runs).
- [ ] **Task 3.2: Smart Save Planner (`core/smart_save`)**
  - Implement `planWindow()`, `makeResult()`, `writeMeta()`, and CLI `--compare` replay verification.
- [ ] **Task 3.3: Online Monitor State Machine & Async Event Writer (`core/monitor_engine`, `core/event_writer`)**
  - Implement `MonitorEngine` (`armed -> recording -> padding -> armed`) with bounded ring buffer (`before + walkback`), left `2/3` column detection crop (`MON_DETECT_FRAC`), trigger `300`, quiet hold `60` frames, end margin `30`, runaway cap `600`, and drip validation (`MON_MIN_PEAK = 3000`).
  - Implement background `EventWriter` thread pool writing BMPs + `injection_meta.json` and emitting completion callbacks without blocking the grab loop.
  - **Verification Gate**: Port `tests/test_injection_bounds.py`, `tests/test_gel_end_rule.py`, `tests/test_smart_save.py`, `tests/test_monitor_engine.py`, and `tests/test_frame_writer.py` to GoogleTest.

---

### Phase 4: Piston Tracking, Speed Curves & Batch Summary (`hsc_core`)
**Objective**: Port the complete piston tracking and hydrodynamic calculation pipeline.

- [ ] **Task 4.1: Barrel Profiling, Edge Modes & Common Slope (`core/piston_track`)**
  - Implement `buildProfile()` (temporal max/min over 60 frames, bright row band, `_restrictToBody` sweep test, 12% inset, short-ROI detection `<= 80` rows).
  - Implement `edgeColumns()` (`MIN_BODY_RUN = 30`, `MIN_BORDER_RUN = 8`, `BODY_DARK_FRAC = 0.08`, parabolic gradient offset, and `_walkToVisible` for short ROIs).
  - Implement `refineBand()` (`AGREE_TOL = 2.0 px`) and `chooseEdgeMode()` (`global`, `row-frac`, `row-mid` straightness & coverage contest).
  - Implement `commonSlope()`, `applyCommonSlope()`, and `lineDistance()`.
- [ ] **Task 4.2: Fast Coarse-to-Fine Scanner & Stroke Bounds (`core/piston_track`)**
  - Implement multi-threaded `scanPositions()` (`SCAN_STRIDE = 8`, `SCAN_WORKERS = 8`, `_motionBracket()`).
  - Implement `locateStroke()` (for full bursts) and `detectPistonBounds()` (for extracted windows: `MOVE_TRAVEL_FRAC = 0.05`, local step walk-back `ONSET_SPEED_FRAC = 0.25`, plateau hold `15` frames, `implausibleSteps` `> 10.0 px`).
- [ ] **Task 4.3: Piston Speed, Timebase Inference, Curves & Summary (`core/measure_piston`, `core/piston_plot`, `core/summary`)**
  - Implement `resolveTimebase()` (inferring `us`, `ns`, `ms` tick unit against measured FPS within `TIMEBASE_TOL = 0.05`).
  - Implement Savitzky-Golay velocity derivative, `jetFromPiston()` ($v_{\text{jet}}$ and $P_{\text{stagnation}}$), `PistonPlot` OpenCV chart generator (with 1/2/5 nice ticks and NaN gap breaks), and `<run>_speed.csv` writer.
  - Implement `Summary` cross-run aggregator (`n, mean, std, cv_percent, min, median, max` + skipped folder audit).
  - **Verification Gate**: Port `tests/test_piston_track.py`, `tests/test_piston_speed.py`, and `tests/test_summary.py` to GoogleTest.

---

### Phase 5: Spatial Calibration, Nozzle Reference & Video Synthesis (`hsc_core`)
**Objective**: Port the setup, metrology, and video generation modules.

- [ ] **Task 5.1: Scale Calibration & Angle Block (`core/calibrate_scale`, `core/measure_block`)**
  - Implement `detectEdgeInRoi()` (`step`, `outer`, `dark`, `bright`), `autoRois()` (left-1/3 scanline voting `_twoEdgesBright` vs `_twoLines`), `autoCalibrateImage()`, and `measureBlockSize()`.
  - Implement `measureBlock()` for angle blocks (`block_angles.csv`).
- [ ] **Task 5.2: Nozzle Reference & Video Writer (`core/reference_lines`, `core/make_video`)**
  - Implement `buildReference()`, `attachRectangle()`, and `drawReference()`.
  - Implement `makeVideo()` (`slowmo.mp4` at 15 fps, filtering to largest same-size frame group so piston measure folders with plot PNGs compile cleanly).
  - **Verification Gate**: Port `tests/test_calibrate_block.py`, `tests/test_calibration.py`, and `tests/test_ref_lines_toggle.py` to GoogleTest.

---

### Phase 6: Persistent Camera Worker & Redesigned Qt 6 GUI (`hsc_camera`, `hsc_gui`)
**Objective**: Upgrade `C version/gui/` into the complete, modern Qt 6 desktop application.

- [ ] **Task 6.1: Persistent `CameraWorker` Upgrade (`camera/camera_worker`)**
  - Refactor `CameraController` so the camera stays open continuously during Live Preview and transitions instantaneously into:
    1. Still grab (for Calibration, Reference, Block measurement).
    2. Spray Burst Capture (with in-RAM Smart Save option).
    3. Piston Burst Capture (recording per-frame `blockId` and `timeStamp` into `piston_capture.json` and reporting dropped frames).
    4. Gel Burst Capture (routing to `end_rule="temporal"`).
    5. Continuous Monitor Loop (feeding `MonitorEngine` while keeping live preview active).
- [ ] **Task 6.2: Main Window UX Overhaul (`gui/main_window`, `gui/results_inspector`)**
  - Build the persistent Top Status Header (with live Scale & Reference validity/mismatch badges).
  - Build the 6 Mode Tabs, the permanently visible Bottom-Left Action Bar (with Spacebar shortcut), and the 4-stage Visual Pipeline Stepper.
  - Build the dual-tab Viewport (`Live Preview` with live reference overlay + `Results Inspector` with KPI cards, frame scrubber, and curve tabs).
- [ ] **Task 6.3: Interactive Zoomable Setup Dialogs (`gui/calibration_dialog`, `gui/reference_dialog`, `gui/summary_dialog`)**
  - `CalibrationDialog`: Zoomable `QGraphicsView` for dragging ROI 1 and ROI 2, live green edge detection preview, pixel gap, and `mm/px` confirmation.
  - `ReferenceDialog`: Zoomable `QGraphicsView` for dragging the yellow nozzle tip line, live perpendicular blue spray axis and red target rectangle preview.
  - `SummaryDialog`: Multi-run checklist picker, live statistical table with `CV%` highlighting, and CSV export.

---

### Phase 7: Packaging, Self-Test & Rig Acceptance
**Objective**: Deliver a one-folder portable Windows build verified against real rig data.

- [ ] **Task 7.1: Headless Self-Test & CLI (`hsc_cli`)**
  - Implement `hsc_gui.exe --selftest "<injection_folder>"` (runs angle measurement + slow-mo video headlessly and writes `selftest.log`).
- [ ] **Task 7.2: Portable Deployment Script (`package_portable.bat`)**
  - Automate CMake Release build, `windeployqt`, OpenCV DLL copying, and IMV `Runtime/x64` bundling into `dist/HighSpeedCamera/`.
- [ ] **Task 7.3: Feature Decoupling & Stripped-Build Verification**
  - Build with individual features turned off (e.g. Spray-only build: `-DHSC_ENABLE_PISTON=OFF -DHSC_ENABLE_GEL=OFF -DHSC_ENABLE_SUMMARY=OFF`; Piston-only build: `-DHSC_ENABLE_SPRAY_ANGLE=OFF -DHSC_ENABLE_MONITOR=OFF`) and verify clean compilation, zero linker errors, and automatic tab adaptation.
- [ ] **Task 7.4: Golden Burst Parity Acceptance**
  - Replay recorded rig bursts (`data/captures/*`) through both Python and C++ builds and verify identical CSV reports and annotated overlays.

---

## 6. Summary Schedule & Effort Estimate

| Phase | Deliverable | Key Risk Mitigated |
| :--- | :--- | :--- |
| **Phase 1** | CMake + JSON + BMP I/O (`biHeight` sign handling) | Prevents upside-down monitor/cv2 frames. |
| **Phase 2** | Spray Angle Core (`erf`, RANSAC, TLS, Quality) | Proven against synthetic wedge ground truth before UI work. |
| **Phase 3** | Injection Extractor + Smart Save + Monitor FSM | Ensures online drip rejection & gel temporal end-rule parity. |
| **Phase 4** | Piston Tracker + Timebase Inference + Hydrodynamics | Preserves all hard-won rig fixes (collar stripe, common slope, local step walk-back). |
| **Phase 5** | Calibration + Nozzle Reference + Video | Complete offline capability via CLI & unit tests. |
| **Phase 6** | Persistent Camera Thread + Redesigned Qt 6 UX | Solves all Tkinter UI clutter and silent mismatch pitfalls. |
| **Phase 7** | Portable `dist/` Bundle + Golden Dataset Validation | Zero-dependency deployment on test rig PCs. |
