# Building & Transferring the App (Windows .exe)

The GUI can be packaged into a standalone Windows folder app with
[PyInstaller](https://pyinstaller.org/) so it runs on another PC **without
installing Python or any packages**.

## Build

One time, on the development PC:

```
pip install pyinstaller
```

Then build (run from this folder):

```
build_exe.bat
```

or directly:

```
pyinstaller HighSpeedCamera.spec --noconfirm
```

Output: **`dist\HighSpeedCamera\`** containing `HighSpeedCamera.exe` and an
`_internal\` folder (Python runtime, OpenCV/SciPy/scikit-learn, the camera SDK
wrapper, the `Runtime\x64` camera DLLs, and `injection_scan.exe`). ~480 MB
uncompressed, ~150–200 MB zipped.

## Transfer

1. **Zip the whole `dist\HighSpeedCamera` folder** (not just the .exe — the
   `_internal` folder must travel with it).
2. Copy the zip to the other PC and unzip it anywhere.
3. Run `HighSpeedCamera.exe`.

Captures, `injection images`, and `measure` output are written **next to the
.exe**, so keep it in a folder the user can write to (not `C:\Program Files`).

## What the target PC needs

- **Nothing for measurement / video** — the packaged app is self-contained.
  `HighSpeedCamera.exe --selftest "<an injection images folder>"` runs the
  measure + video pipeline with no camera and writes the result to
  `selftest.log` next to the exe (use it to confirm a fresh copy works).
- **For live capture** — the physical high-speed camera plus its USB3 Vision /
  vendor driver installed on that PC. The app bundles the SDK **runtime DLLs**,
  but the OS-level camera driver is installed by the camera vendor's installer.

## Verify a build

```
HighSpeedCamera.exe --selftest "D:\path\to\injection images\<run>"
```

`selftest.log` should end with `SELFTEST PASSED`.

## Rebuilding notes

- Close the app before rebuilding (a running exe locks `dist\`).
- The console window is hidden (`console=False` in `HighSpeedCamera.spec`). Set
  it to `True` and rebuild if you want a debug console with stdout tracebacks.
- `build\` and `dist\` are git-ignored (regenerable).
