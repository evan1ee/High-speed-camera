# CLAUDE.md

Guidance for working in this project (the **C/C++ version** of the high-speed
camera spray-angle capture tool).

## What this is

Two programs that drive a Huaray/iRayple industrial high-speed camera through the
**IMV C SDK** (`MVSDKmd.lib` / `MVSDKmd.dll`, MSVC):

1. **`capture_image_cpp.cpp`** — a command-line capture tool. Configures the
   camera, grabs frames for a fixed duration, and saves them (deferred-save by
   default) into a timestamped folder.
2. **`gui/`** — a Qt 6 Widgets desktop GUI that does the same thing plus live
   preview, by linking the IMV SDK directly and running capture/preview on a
   worker thread. It does **not** shell out to the CLI.

The CLI and GUI are independent builds; changing one does not require rebuilding
the other.

## Repository layout

```
C version/
├── capture_image_cpp.cpp     # CLI tool (single file)
├── CMakeLists.txt            # CLI build (CMake)
├── build_msvc.bat            # CLI build (direct cl.exe)
├── run_capture.bat           # CLI run wrapper (sets PATH for IMV DLLs)
├── README.md                 # CLI docs
├── Development/Include/IMV/   # IMVApi.h, IMVDefines.h  (local SDK copy)
├── Development/Lib/x64/       # MVSDKmd.lib             (local SDK copy)
├── Runtime/x64/              # MVSDKmd.dll + deps       (local SDK copy, needed at runtime)
├── captures/                 # Output frames (generated; do not edit by hand)
└── gui/
    ├── camera_controller.{h,cpp}  # IMV SDK worker (QThread): enumerate/configure/preview/capture
    ├── main_window.{h,cpp}        # Qt Widgets UI + threading wiring
    ├── main.cpp                   # entry point
    ├── CMakeLists.txt
    ├── build_gui.bat / run_gui.bat
    └── README.md
```

The project is **self-contained**: the IMV SDK headers, import library, and
runtime DLLs are vendored locally under `C version/` (the `SDK_ROOT` for both
CMake files is this folder). It no longer reads anything from the parent
`High speed camera/` directory. If you upgrade the SDK, refresh these three
folders from the new SDK release.

Reference docs in the parent folder: `Industrial Camera SDK Development
Document (C Interface)_Ver2.3.pdf`, `IMV_API_C_ENG.chm`. There is also a Python
sibling implementation (`../capture_image.py`, `../capture_gui.py`) that defines
the original behavior and UX — keep parity with it when in doubt.

## Toolchain (this machine)

- **Qt**: 6.11.1, MSVC kit at `D:\Qt\6.11.1\msvc2022_64`. Qt MUST be the MSVC
  build — the IMV import lib is MSVC, so a MinGW Qt will not link.
- **Compiler**: Visual Studio 2022 Community (`C:\Program Files\Microsoft Visual Studio\2022\Community`).
- **CMake**: 3.31 on PATH.

## Build & run

**CLI** (from an *x64 Native Tools Command Prompt for VS*, or let the script init VS):
```bat
build_msvc.bat          :: produces build\capture_image_cpp.exe
run_capture.bat --list  :: run; wrapper prepends ..\Runtime\x64 to PATH
```

**GUI**:
```bat
cd gui
build_gui.bat   :: cmake (VS 2022 generator) + windeployqt; override kit with: set QT_DIR=...
run_gui.bat     :: prepends ..\..\Runtime\x64 to PATH for MVSDKmd.dll
```

Both run wrappers exist because the executables need `Runtime\x64` on `PATH` to
find `MVSDKmd.dll`. Always launch through the `.bat` wrappers, not the raw exe.

## SDK call pattern (do not break this order)

`IMV_EnumDevices` → `IMV_CreateHandle(modeByIndex, &zeroBasedIndex)` → `IMV_Open`
→ set features (`TriggerMode=Off`, `PixelFormat`, ROI `Width/Height/OffsetX/OffsetY`,
`ExposureTime`) → `IMV_StartGrabbing` → loop `IMV_GetFrame` (+ optional
`IMV_CloneFrame` for deferred save) → `IMV_ReleaseFrame` → `IMV_StopGrabbing` →
`IMV_Close` → `IMV_DestroyHandle`.

Key facts:
- Camera index is **1-based** in the UI/CLI, **0-based** in `IMV_CreateHandle`.
- Every `IMV_GetFrame` must be matched by `IMV_ReleaseFrame`; every
  `IMV_CloneFrame` must be released too. Release on error paths.
- Preview assumes **Mono8** (1 byte/pixel → `QImage::Format_Grayscale8`); copy the
  image before releasing the frame (the SDK owns the buffer).
- SDK functions return `IMV_OK` on success; check return codes and surface the
  numeric error code in logs.

## Conventions

- C++17, MSVC `/W4`. Keep the CLI as a single translation unit; keep the GUI as
  small, focused files (controller / window / main).
- GUI threading: all camera work runs in `CameraController` on a `QThread`. The
  UI talks to it via `QMetaObject::invokeMethod(..., Qt::QueuedConnection)` and
  receives results via signals. Stop requests use `std::atomic` flags because the
  grab loop blocks the worker's event loop.
- `CaptureSettings` crosses threads via queued calls — it is registered with
  `qRegisterMetaType` in `main.cpp`; keep it copyable.
- Don't hand-edit `captures/` or `build/` — they are generated.

## Aspect presets (width × height)

`1:1` 332×332 · `2:1` 664×332 · `4:3` 432×324 · `16:9` 576×324 · `320x240` 320×240.
These are duplicated in the CLI (`kAspectPresets`) and GUI (`kAspectPresets`);
update both if you change them.
