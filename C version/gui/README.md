# Qt GUI for the C++ capture app

A Qt 6 (Widgets) desktop GUI for the high-speed camera capture workflow. It is
the C++/Qt counterpart of the Python `capture_gui.py`, but instead of shelling
out to an `.exe` it drives the Huaray/iRayple **IMV C SDK** directly in a worker
thread, so live preview and burst capture share one code path.

The original CLI (`capture_image_cpp.cpp`) is untouched and still builds.

## Features

- **Capture Settings**: capture time, aspect preset (1:1 / 2:1 / 4:3 / 16:9 / 320x240),
  exposure (µs), camera index, image type, output base folder + Browse, and the
  Defer save / Timestamp folder / Test-only checkboxes.
- **Live Preview**: real-time Mono8 preview from the selected camera.
- **Run Capture**: deferred-save burst (clone during grab, save after stop) into a
  timestamped folder, exactly like the CLI.
- **Stop / Open Last Folder / Refresh Devices** and a status line + output log.

## Layout

| File | Role |
|------|------|
| `camera_controller.{h,cpp}` | IMV SDK worker (enumerate, configure, preview, capture) on a `QThread`; communicates via signals/slots. |
| `main_window.{h,cpp}` | Widgets UI, threading wiring, preview rendering, log. |
| `main.cpp` | App entry point; registers `CaptureSettings` as a queued-call metatype. |
| `CMakeLists.txt` | Qt6 + IMV SDK build. |
| `build_gui.bat` / `run_gui.bat` | Configure/build/deploy, then launch. |
| `package_portable.bat` | Bundle a self-contained, copy-anywhere folder under `dist\`. |

## Build

Requires an **MSVC build of Qt 6** (the IMV import lib `MVSDKmd.lib` is MSVC) and
Visual Studio 2022. Detected kit: `D:\Qt\6.11.1\msvc2022_64`.

```bat
cd /d "D:\01_Data\code\spray-angle-test\High speed camera\C version\gui"
build_gui.bat
```

Override the Qt kit if needed:

```bat
set QT_DIR=D:\Qt\6.11.1\msvc2022_64
build_gui.bat
```

`build_gui.bat` configures with the *Visual Studio 17 2022* generator, builds
Release, and runs `windeployqt` to copy Qt DLLs next to the executable.

## Run

```bat
run_gui.bat
```

`run_gui.bat` prepends the project-local `..\Runtime\x64` to `PATH` so Windows
can load `MVSDKmd.dll` and its dependencies, just like `run_capture.bat`. The
SDK is vendored under `C version/` — nothing is read from the parent folder.

## Deploy to another PC

The bare `capture_gui_qt.exe` will not run elsewhere on its own — it needs the
Qt DLLs, the IMV SDK DLLs, and the MSVC runtime. `package_portable.bat` bundles
all of them next to the exe so the result is copy-anywhere:

```bat
build_gui.bat          :: build first (produces build\Release)
package_portable.bat   :: bundle -> dist\capture_gui_qt\
```

This produces a self-contained folder:

```
gui\dist\capture_gui_qt\
├── capture_gui_qt.exe
├── Qt6*.dll, platforms\, imageformats\, ...   (from windeployqt)
└── MVSDKmd.dll + deps, msvcp140.dll, vcruntime140*.dll   (from Runtime\x64)
```

Copy the **whole folder** (or zip it) to the target machine and double-click
`capture_gui_qt.exe` — no `PATH` setup needed, because every DLL sits next to
the exe.

Target-machine requirements:

- **Windows 64-bit** (this is an x64 build).
- The **camera USB driver** installed once (e.g. MVViewer / the iRayple driver
  package). DLLs do not install a USB driver.

Common failures: a missing `platforms\` subfolder (you copied loose files
instead of the whole folder), or the camera driver not being installed.
