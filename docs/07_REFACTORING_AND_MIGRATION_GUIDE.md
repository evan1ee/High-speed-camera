# Refactoring & Language Migration Guide

This document provides a technical roadmap, architectural blueprint, component gap analysis, and implementation strategy for refactoring and porting the needle-free injector test toolkit to high-performance compiled languages (specifically modern C++20 / Qt 6 or Rust).

---

## 1. Motivation & Refactoring Objectives

### 1.1 Why Port from Python to C++ / Rust?
1. **Single Unified Runtime**: The current system relies on a dual-stack configuration (Python for analysis, C++ for camera DLLs and the `injection_scan.exe` motion scanner). Porting creates a single native binary without Python runtime or `uv` environment setup.
2. **Deterministic Real-Time Performance**: Eliminates Python Global Interpreter Lock (GIL) contention and garbage collection pauses during high-rate bursts (1,000 to 2,600+ fps).
3. **Zero-Copy In-Memory Pipeline**: Allows direct analysis of camera DMA frame buffers in RAM, avoiding unnecessary BMP encoding and disk round-trips.
4. **Lightweight Distribution**: Python PyInstaller bundles are $\sim 150\ \text{MB}$ and extract to temporary directories on launch. A native C++ / Qt6 or Rust release binary is $\sim 15\dots25\ \text{MB}$ and launches instantaneously.

---

## 2. Component Migration & Parity Status: Python vs. C++20 / Qt 6

The modern C++20 / Qt 6 implementation in `C version/` now achieves complete functional, algorithmic, and schema parity with the Python reference implementation. Every subsystem is structured as an isolated vertical feature slice in `src/features/` with self-registration and automated testing:

| Feature / Subsystem | Python Reference (`High speed camera/`) | C++20 / Qt 6 Implementation (`C version/`) | Parity & Implementation Status |
| :--- | :--- | :--- | :--- |
| **Camera Enumeration & Open** | `hsc/capture_image.py` | `camera_controller.cpp` | **Complete**: Native IMV SDK wrapper with thread-safe acquisition loop. |
| **Live Preview (Mono8)** | `hsc/gui/camera_worker.py` | `viewport_widget.cpp`, `main_window.cpp` | **Complete**: Real-time QImage / OpenGL rendering with geometry overlays. |
| **Deferred Burst Capture** | `hsc/capture_image.py` | `capture_image_cpp.cpp`, `camera_controller.cpp` | **Complete**: High-throughput memory buffer with deferred disk writer. |
| **Hardware Timestamps & blockId** | Saved to `piston_capture.json` | `camera_controller.cpp` | **Complete**: Hardware timestamp extraction and `piston_capture.json` export. |
| **Fast Motion Scanner** | `native/injection_scan.cpp` | `src/foundation/temporal_scanner.cpp` | **Complete**: SIMD/OpenMP-accelerated raw BMP diffing and window detection. |
| **Temporal & Presence Extraction** | `hsc/injection_extract.py` | `src/features/gel/gel_feature.cpp`, `src/features/spray_angle/` | **Complete**: Dual-rule presence and temporal motion event extractors. |
| **Smart Save (Detect-in-RAM)** | `hsc/smart_save.py` | `src/features/spray_angle/smart_save.cpp` | **Complete**: Online variance/pixel threshold scan discarding idle frames before disk write. |
| **Online Streaming Monitor** | `hsc/monitor.py`, `frame_writer.py` | `src/features/monitor/` (`monitor_engine.cpp`) | **Complete**: Multi-state FSM (ARMED, RECORDING, PADDING) for continuous unattended monitoring. |
| **Spray Angle Pipeline** | `hsc/measure_angle.py` | `src/features/spray_angle/` (`measure_angle.cpp`, `erf_edge.cpp`) | **Complete**: Otsu thresholding, erf subpixel edge fitting, Savitzky-Golay filtering, RANSAC, TLS PCA line fit. |
| **Piston Tracking Pipeline** | `hsc/piston_track.py` | `src/features/piston/piston_track.cpp` | **Complete**: Ampoule barrel band extraction, subpixel step edge tracking, common slope constraint. |
| **Piston Speed & Hydrodynamics** | `hsc/measure_piston.py` | `src/features/piston/measure_piston.cpp` | **Complete**: Multi-unit timebase inference, Savitzky-Golay velocity derivation, Bernoulli exit velocity & stagnation pressure. |
| **Spatial Calibration (mm/px)** | `hsc/calibrate_scale.py`, UI | `src/features/calibration/` (`calibrate_scale.cpp`, `calibration_dialog.cpp`) | **Complete**: Auto 1-click gauge block detection and interactive zoomable manual ROI dialog. |
| **Nozzle Reference Setup** | `hsc/reference_lines.py`, UI | `src/features/reference/` (`reference_dialog.cpp`, `reference_store.cpp`) | **Complete**: Interactive tip line, spray axis centerline, and target tolerance box editor. |
| **Angle Block Verification** | `hsc/measure_block.py` | `src/features/angle_block/` (`measure_block.cpp`) | **Complete**: Gaussian blur, Otsu thresholding, 8-connected component edge detection & angle validation. |
| **Slow-Motion Video Synthesis** | `hsc/make_video.py` | `src/foundation/make_video.cpp` | **Complete**: Standalone AVI 1.0 uncompressed DIB writer with frame timing and annotations. |
| **Cross-Run Summary Analysis** | `hsc/summary.py`, `gui/summary.py` | `src/features/summary/` (`summary_feature.cpp`, `summary_calc.cpp`) | **Complete**: Batch CSV scanner, mean, std, min, max, CV% statistical calculation and report generation. |
| **Automated Verification Harness** | `tests/` (Python `pytest`) | `tests/test_main.cpp` (`hsc_tests.exe`) | **Complete**: 124 passing unit tests covering all core algorithms and features. |

---

## 3. Recommended Target Architecture

A clean, modular 3-tier architecture is recommended for the C++ refactoring:

```
┌─────────────────────────────────────────────────────────────┐
│                 Presentation Layer (Qt 6)                   │
│   MainWindow  │  CalibrationDialog  │  ReferenceDialog      │
│   SummaryView │  LivePreviewWidget  │  CurvePlotWidget      │
└──────────────────────────────┬──────────────────────────────┘
                               │ Signals / Slots
┌──────────────────────────────▼──────────────────────────────┐
│                  Application / Engine Layer                 │
│   CaptureEngine   │   StreamingMonitorEngine   │   Chainer  │
└──────────────────────────────┬──────────────────────────────┘
                               │ C++ API
┌──────────────────────────────▼──────────────────────────────┐
│                  Core Algorithmic Library                   │
│   libinjector_core (Header-only or Static Library)          │
│   - MotionScanner          - SprayAngleDetector             │
│   - InjectionExtractor     - PistonTracker                  │
│   - TotalLeastSquaresFit   - SavitzkyGolayDerivative        │
│   - HydrodynamicCalculator - CalibrationMath                │
└──────────────────────────────┬──────────────────────────────┘
                               │ Drivers / Vendor
┌──────────────────────────────▼──────────────────────────────┐
│              Hardware Layer: IMV C SDK Linkage              │
│   MVSDKmd.dll  │  MVProducerU3V.cti  │  IMVApi.h            │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 Design Principles
1. **Headless Core (`libinjector_core`)**: The mathematical and computer vision core must have **zero UI dependencies** (no Qt Widgets, no GUI headers). It should depend only on the standard library, OpenCV C++ (`core`, `imgproc`), and linear algebra (`Eigen` or OpenCV).
2. **Full Unit Testability**: The core library can be thoroughly tested via Google Test (`gtest`) or Catch2 against synthetic ground-truth datasets without a camera or display server.
3. **State Isolation**: Encapsulate camera state machines cleanly. Capture loops run on background worker threads (`std::jthread` or `QThread`).

---

## 4. Library & API Mapping (Python $\to$ C++)

| Python Library / Function | Recommended C++ Equivalent | Implementation Notes |
| :--- | :--- | :--- |
| `cv2.GaussianBlur` | `cv::GaussianBlur` | Identical parameterization (`cv::Size(5, 5)`, $\sigma=0$). |
| `cv2.threshold(..., THRESH_OTSU)` | `cv::threshold` | Direct drop-in. |
| `cv2.connectedComponentsWithStats` | `cv::connectedComponentsWithStats` | Direct drop-in (`labels`, `stats`, `centroids`). |
| `scipy.ndimage.gaussian_filter1d` | 1D separable convolution | Custom 1D Gaussian kernel or `cv::sepFilter2D`. |
| `scipy.special.erf` | `std::erf` | Standard C++11 `<cmath>` header. |
| `scipy.optimize.curve_fit` | Ceres Solver / levmar / Custom LM | Levenberg-Marquardt solver for the 4-parameter erf step model. |
| `sklearn.linear_model.RANSACRegressor` | Custom C++ RANSAC template | Simple 2-point RANSAC loop over 2D point vector ($\le 50$ lines). |
| Total Least Squares (PCA) | `cv::PCA` or `Eigen::SelfAdjointEigenSolver` | $2 \times 2$ covariance matrix eigendecomposition. |
| `scipy.signal.savgol_filter` | Analytical FIR Convolution Kernel | Precompute Gram polynomial matrix weights for $(W=15, \text{poly}=2, \text{deriv}=1)$. |
| `json.loads` / `json.dumps` | `nlohmann/json` | Header-only, modern C++ JSON manipulation. |
| `piston_plot.py` (Canvas plotting) | Custom `QPainter` or `QCustomPlot` | `QPainter` drawing directly on widget or image buffer. |
| `make_video.py` (`cv2.VideoWriter`) | `cv::VideoWriter` | Use codec `'m', 'p', '4', 'v'` or `'M', 'J', 'P', 'G'`. |

---

## 5. Algorithmic Reimplementation Specifications

### 5.1 Savitzky-Golay Numerical Derivative (C++)
In Python, `scipy.signal.savgol_filter(x, window_length=15, polyorder=2, deriv=1, delta=dt)` computes the velocity. In C++, implement this via a precomputed FIR convolution filter:

```cpp
// Precomputed Savitzky-Golay coefficients for window=15, poly=2, deriv=1
// Convolved with displacement series d[i] to yield velocity v[i] = (sum(c[k]*d[i+k])) / (delta_t * norm)
static const int kSGWindow = 15;
static const int kSGHalf = 7;
static const double kSGCoeffs[15] = {
    -7.0, -6.0, -5.0, -4.0, -3.0, -2.0, -1.0,
     0.0,
     1.0,  2.0,  3.0,  4.0,  5.0,  6.0,  7.0
};
static const double kSGNorm = 280.0; // sum(k^2) from -7 to 7

inline double computeSGDerivativeAt(const double* d, double dt) {
    double sum = 0.0;
    for (int k = -kSGHalf; k <= kSGHalf; ++k) {
        sum += kSGCoeffs[k + kSGHalf] * d[k];
    }
    return sum / (dt * kSGNorm);
}
```

### 5.2 Total Least Squares (TLS) Orthogonal Line Fitting (C++)
Given 2D inlier points $(x_i, y_i)$:

```cpp
struct TlsLine {
    double slope;
    double intercept;
    double vx;
    double vy;
};

inline TlsLine fitTls(const std::vector<cv::Point2d>& pts) {
    const size_t n = pts.size();
    if (n < 2) return {0, 0, 1, 0};

    // 1. Centroid
    double mx = 0.0, my = 0.0;
    for (const auto& p : pts) { mx += p.x; my += p.y; }
    mx /= n; my /= n;

    // 2. 2x2 Covariance
    double cxx = 0.0, cxy = 0.0, cyy = 0.0;
    for (const auto& p : pts) {
        double dx = p.x - mx;
        double dy = p.y - my;
        cxx += dx * dx;
        cxy += dx * dy;
        cyy += dy * dy;
    }

    // 3. Eigendecomposition of 2x2 symmetric matrix
    // Analytical solution for 2x2 eigenvalues
    double trace = cxx + cyy;
    double det = cxx * cyy - cxy * cxy;
    double diff = std::sqrt(std::max(0.0, trace * trace - 4.0 * det));
    double lambda_max = 0.5 * (trace + diff);

    // Eigenvector corresponding to lambda_max
    double vx = cxy;
    double vy = lambda_max - cxx;
    double norm = std::hypot(vx, vy);
    if (norm < 1e-12) {
        vx = 1.0; vy = 0.0;
    } else {
        vx /= norm; vy /= norm;
    }
    if (vx < 0.0) { vx = -vx; vy = -vy; } // Canonical orientation

    double slope = (std::abs(vx) > 1e-12) ? (vy / vx) : (std::copysign(1e12, vy));
    double intercept = my - slope * mx;

    return {slope, intercept, vx, vy};
}
```

### 5.3 Sub-Pixel Parabolic Interpolation (C++)
```cpp
inline double parabolicVertexOffset(double a, double b, double c) {
    double denom = a - 2.0 * b + c;
    if (denom == 0.0) return 0.0;
    double offset = 0.5 * (a - c) / denom;
    if (!std::isfinite(offset) || std::abs(offset) > 0.5) return 0.0;
    return offset;
}
```

---

## 6. High-Performance Optimization Opportunities

When refactoring in C++ or Rust, take advantage of compiled language capabilities:

1. **AVX2 / AVX-512 SIMD Motion Diff**:
   - The motion scanner counts pixels where $|I_t(x) - I_{t-1}(x)| > 25$.
   - Using AVX2 `_mm256_subs_epu8` (saturating unsigned difference), 32 pixels can be evaluated in a single CPU instruction cycle:
     $$\text{abs\_diff} = \operatorname{or}\left( \operatorname{subs}(a, b), \operatorname{subs}(b, a) \right)$$
   - Scanning a 4,000-frame burst at $320 \times 240$ takes $< 50\ \text{ms}$ in RAM.
2. **Zero-Copy Smart Save**:
   - In Python, Smart save computes the motion signal across numpy slices, then calls Python `shutil.copy` or `cv2.imwrite`.
   - In C++, the RAM burst buffer holds `std::vector<std::vector<uint8_t>>`. If an injection is found, write only the window frames directly to disk using multi-threaded asynchronous writes (`std::async` or `QThreadPool`).
3. **Lock-Free SPSC Ring Buffer for Live Preview**:
   - Replace Python `queue.Queue` with a single-producer single-consumer lock-free ring buffer for preview rendering, guaranteeing zero thread synchronization overhead between the camera thread and the UI.

---

## 7. Numerical Verification & Parity Testing Strategy

To ensure the refactored C++ or Rust implementation is completely backward-compatible and produces identical results to the validated Python codebase:

### 7.1 Synthetic Wedges Parity Test
- Reproduce `benchmark/synthetic.py` in C++.
- Generate synthetic spray wedges across known half-angles ($1^\circ, 2^\circ, 3^\circ, 5^\circ, 8^\circ$) with varying noise and blur.
- **Assertion**: C++ TLS fitted slopes must match Python fitted slopes within $\mathbf{\pm 0.0001\ \text{slope}}$ ($< 0.01^\circ$).

### 7.2 Synthetic Piston Stroke Parity Test
- Reproduce `tests/test_piston_track.py` (`make_run`) in C++.
- Generate synthetic strokes with known edge locations ($x = 40.0 \dots 140.0$), tilts, and simulated collar reflections.
- **Assertion**: Piston stroke bounds $(t_{\text{start}}, t_{\text{end}})$ and displacement measurements must match Python to within $\mathbf{\pm 0.05\ \text{px}}$.

### 7.3 Golden Dataset Replay
- Select 5 representative recorded bursts from the rig:
  1. Standard clear water jet in air (`320x240`).
  2. Piston travel run with timestamps (`320x240`).
  3. Short ROI piston travel (`320x120`).
  4. Gel injection run (`320x240`).
  5. Multi-shot monitor run.
- Execute both the Python pipeline and the refactored C++ pipeline against these folders.
- Diff the generated CSVs (`<run>_angles.csv`, `<run>_speed.csv`):
  - Angles must agree within $\mathbf{0.02^\circ}$.
  - Peak piston velocities must agree within $\mathbf{0.5\ \text{mm/s}}$.
  - Stagnation impact pressures must agree within $\mathbf{0.2\ \text{MPa}}$.
