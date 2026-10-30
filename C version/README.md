# High-Speed Camera Needle-Free Injector Analysis Toolkit (C++20 & Qt 6)

Complete modern C++20 and Qt 6 refactoring of the Needle-Free Injector Toolkit, migrating the Python analysis workflows (`High speed camera/`) and technical specifications (`docs/01_...` through `09_...`) to high-performance native desktop architecture with algorithmic and numerical parity.

## Architecture

The project is structured into three decoupled layers:

```
C version/
├── src/
│   ├── foundation/            # Zero-Qt / Pure C++20 Core Algorithms & I/O
│   │   ├── app_paths.{h,cpp}          # Atomic JSON persistence & path resolvers
│   │   ├── bmp_io.{h,cpp}             # Zero-copy 8-bit uncompressed BMP parser/encoder
│   │   ├── calibration_store.{h,cpp}  # Scale calibration store (px/mm)
│   │   ├── reference_store.{h,cpp}    # Nozzle tip, spray centerline, ROI containment
│   │   ├── tls_fit.{h,cpp}            # Robust sigma, subpixel offsets, TLS/PCA, RANSAC, SG filter
│   │   ├── temporal_scanner.{h,cpp}   # OpenMP motion scanner & dual-rule injection bounds
│   │   ├── summary_calc.{h,cpp}       # Batch metrics aggregator & CSV export
│   │   └── make_video.{h,cpp}         # Native uncompressed DIB AVI writer
│   ├── features/              # Feature modules conforming to specifications
│   │   ├── spray_angle/               # 4-parameter erf step solver, Otsu, candidate contest, TLS
│   │   ├── piston/                    # Dark edge tracking, common slope pooling, hydrodynamics
│   │   ├── gel/                       # Gel penetration motion scanner & AVI video pipeline
│   │   ├── calibration/               # Dual ROI edge detector & scale calibration dialog
│   │   ├── reference/                 # Interactive nozzle reference alignment dialog
│   │   ├── angle_block/               # Machined block verification & deviation metrics
│   │   ├── monitor/                   # Real-time FSM (Armed/Recording/Padding) & async disk writer
│   │   └── summary/                   # Batch statistical aggregator & cross-run CSV reporter
│   └── shell/                 # Decoupled UI Service Broker & Viewport
│       ├── i_feature_module.h         # Feature slice abstraction & lifecycle hooks
│       ├── feature_registry.{h,cpp}   # Dynamic feature registry & Open-Closed auto-registration
│       ├── pipeline_runner.{h,cpp}    # Async background task orchestrator
│       ├── app_services.{h,cpp}       # Service broker
│       ├── inspection_report.h        # Unified KPI cards & chart report model
│       └── viewport_widget.{h,cpp}    # Zoomable QGraphicsView with overlay & KPI cards
├── gui/                       # Main application shell
│   ├── main_window.{h,cpp}            # Split-viewport UX, dynamic registry tabs, quick parameter bar
│   ├── camera_controller.{h,cpp}      # IMV camera abstraction & preview thread with timestamp logging
│   ├── build_gui.bat                  # CMake configure, build & windeployqt
│   └── run_gui.bat                    # Sets Runtime\x64 PATH and launches application
└── tests/                     # Verification test suite
    └── test_main.cpp                  # 13 test suites, 124 passing assertions
```

## Building and Running

### Prerequisites
- Windows 10/11 x64
- Visual Studio 2022 Community / MSVC v143 toolchain (C++20)
- Qt 6.5+ MSVC kit (e.g. `D:\Qt\6.11.1\msvc2022_64`)
- CMake 3.22+

### 1. Build GUI & Run Standalone
```bat
cd /d "D:\01_Data\code\spray-angle-test\C version\gui"
build_gui.bat
run_gui.bat
```

### 2. Run Test Suite
```bat
set PATH=D:\Qt\6.11.1\msvc2022_64\bin;D:\01_Data\code\spray-angle-test\C version\Runtime\x64;%PATH%
"D:\01_Data\code\spray-angle-test\C version\gui\build\Release\hsc_tests.exe"
```

## Algorithmic Parity Highlights

- **Bmp I/O**: Fast uncompressed 8-bit BMP loader handling both top-down (`biHeight < 0`) and bottom-up (`biHeight > 0`) scanline order with stride alignment.
- **Erf Edge Model**: 4-parameter blurred-step error function ($f(x) = \text{base} + \frac{\text{amp}}{2} [1 \pm \text{erf}(\frac{x - \mu}{\sqrt{2} \sigma})]$) solved with Levenberg-Marquardt and partial-pivoting 4x4 linear algebra.
- **Spray Angle Pipeline**: Otsu automatic thresholding, $5\times 5$ Gaussian kernel, candidate loci contest (argmax gradient vs Otsu contour), RANSAC + Total Least Squares line fitting, and reference line deviation angle verdict.
- **Piston & Hydrodynamics**: Common slope pooling across time series, Savitzky-Golay 2nd order velocity derivation, and hydrodynamic orifice velocity / stagnation impact pressure conversion ($P = \frac{1}{2} \rho v_{\text{jet}}^2$).
- **Continuous Monitoring**: Finite State Machine with sliding ROI pixel-difference trigger, pre-trigger circular frame buffer, post-trigger recording, and drip rejection.
