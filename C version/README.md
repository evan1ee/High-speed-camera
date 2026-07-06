# C++ Image Capture

This is a C++ version of `capture_image.py` using the IMV C SDK.

## Default Capture

Default settings match the Python burst workflow:

- Camera index: `1`
- Aspect preset: `16:9`
- Resolution: `576 x 324`
- Pixel format: `Mono8`
- Exposure: `1000 us`
- Duration: `1 second`
- Save type: `.bmp`
- Output: timestamp folder under `captures/burst_16x9_820fps_cpp`
- Capture first, save after capture using `IMV_CloneFrame`

## Build

Open **x64 Native Tools Command Prompt for VS**, then run:

```bat
cd /d "D:\01_Data\code\spray-angle-test\High speed camera\C version"
build_msvc.bat
```

## Run

```bat
run_capture.bat
```

List cameras:

```bat
run_capture.bat --list
```

Capture with the `320x240` preset:

```bat
run_capture.bat --aspect 320x240 --exposure-us 100 --frame-rate 2000
```

Manual ROI:

```bat
run_capture.bat --width 320 --height 240 --exposure-us 100 --frame-rate 2000
```

FPS test without saving:

```bat
run_capture.bat --aspect 16:9 --no-save
```

## Notes

`run_capture.bat` prepends `Runtime\x64` to `PATH`, so Windows can find `MVSDKmd.dll` and its dependent DLLs.

The program uses the same SDK flow as the Python script:

1. `IMV_EnumDevices`
2. `IMV_CreateHandle`
3. `IMV_Open`
4. Set `TriggerMode=Off`, `PixelFormat`, ROI, offsets, exposure
5. `IMV_StartGrabbing`
6. Repeated `IMV_GetFrame`
7. Optional `IMV_CloneFrame`
8. `IMV_SaveImageToFile`
9. `IMV_ReleaseFrame`
10. `IMV_StopGrabbing`, `IMV_Close`, `IMV_DestroyHandle`
