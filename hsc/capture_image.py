#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import os
import sys
import time
from datetime import datetime
from ctypes import byref, c_double, c_int64, c_void_p
from pathlib import Path


from hsc.app_paths import resource_root

ROOT = resource_root()
SDK_DIR = ROOT / "Development" / "Samples" / "Python" / "IMV" / "MVSDK"
RUNTIME_DIR = ROOT / "Runtime" / ("x64" if sys.maxsize > 2**32 else "Win32")
DLL_DIRECTORY_HANDLES = []


# Default capture setup.
# Edit these values when you want to change the normal capture behavior:
# - "aspect": choose "1:1", "2:1", "4:3", "16:9", or "320x240".
# - "exposure_us": lower value = shorter exposure and potentially higher FPS, but darker image.
# - "duration": capture time in seconds.
# - "burst_dir": base output folder for saved frames.
# - "timestamp_dir": True creates one new timestamp folder for every capture run.
# - "defer_save": True means capture first, save after; this avoids dropped frames at high FPS.
DEFAULT_CAPTURE_CONFIG = {
    "burst": True,
    "duration": 1.0,
    "index": 1,
    "aspect": "16:9",
    "pixel_format": "Mono8",
    "exposure_us": 1000.0,
    "frame_rate": None,
    "defer_save": True,
    "timestamp_dir": True,
    "burst_dir": "captures",
    "ext": ".bmp",
    "prefix": "frame",
}


# Tested 800-1000 FPS ROI presets for AH7040MU000 at Mono8 and about 1000 us exposure.
# Values must follow the camera increment step of 4 pixels.
ASPECT_PRESETS = {
    "1:1": (332, 332),
    "2:1": (664, 332),
    "4:3": (432, 324),
    "16:9": (576, 324),
    "320x240": (320, 240),
}


def load_sdk():
    if not SDK_DIR.exists():
        raise FileNotFoundError(f"SDK Python wrapper not found: {SDK_DIR}")

    old_cwd = os.getcwd()
    sys.path.insert(0, str(SDK_DIR))
    if hasattr(os, "add_dll_directory"):
        DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(RUNTIME_DIR)))
    os.environ["PATH"] = f"{RUNTIME_DIR}{os.pathsep}{os.environ.get('PATH', '')}"
    try:
        # IMVApi.py loads Runtime/x64/MVSDKmd.dll by a relative path, so import it
        # from the wrapper directory.
        os.chdir(SDK_DIR)
        from IMVApi import (  # noqa: WPS433
            IMV_DeviceList,
            IMV_ECreateHandleMode,
            IMV_EInterfaceType,
            IMV_ESaveType,
            IMV_Frame,
            IMV_OK,
            IMV_SaveImageToFileParam,
            IMV_String,
            MvCamera,
            typeGigeCamera,
            typeU3vCamera,
        )
    finally:
        os.chdir(old_cwd)

    return {
        "IMV_DeviceList": IMV_DeviceList,
        "IMV_ECreateHandleMode": IMV_ECreateHandleMode,
        "IMV_EInterfaceType": IMV_EInterfaceType,
        "IMV_ESaveType": IMV_ESaveType,
        "IMV_Frame": IMV_Frame,
        "IMV_OK": IMV_OK,
        "IMV_SaveImageToFileParam": IMV_SaveImageToFileParam,
        "IMV_String": IMV_String,
        "MvCamera": MvCamera,
        "typeGigeCamera": typeGigeCamera,
        "typeU3vCamera": typeU3vCamera,
    }


def check(ret, ok, action):
    if ret != ok:
        raise RuntimeError(f"{action} failed, SDK error code: {ret}")


def feature_available(cam, name):
    try:
        return bool(cam.IMV_FeatureIsAvailable(name))
    except Exception:
        return False


def get_int_feature(cam, name, ok):
    value = c_int64(0)
    ret = cam.IMV_GetIntFeatureValue(name, value)
    check(ret, ok, f"Get {name}")
    return value.value


def get_double_feature(cam, name, ok):
    value = c_double(0.0)
    ret = cam.IMV_GetDoubleFeatureValue(name, value)
    check(ret, ok, f"Get {name}")
    return value.value


def set_int_feature(cam, name, value, ok, required=False):
    if not feature_available(cam, name):
        if required:
            raise RuntimeError(f"Feature is not available: {name}")
        print(f"Skip {name}: not available")
        return False
    ret = cam.IMV_SetIntFeatureValue(name, value)
    if ret != ok:
        if required:
            check(ret, ok, f"Set {name}")
        print(f"Skip {name}: SDK error code {ret}")
        return False
    print(f"Set {name} = {get_int_feature(cam, name, ok)}")
    return True


def get_int_feature_inc(cam, name, ok):
    value = c_int64(0)
    ret = cam.IMV_GetIntFeatureInc(name, value)
    check(ret, ok, f"Get {name} increment")
    return value.value


def set_double_feature(cam, name, value, ok, required=False):
    if not feature_available(cam, name):
        if required:
            raise RuntimeError(f"Feature is not available: {name}")
        print(f"Skip {name}: not available")
        return False
    ret = cam.IMV_SetDoubleFeatureValue(name, value)
    if ret != ok:
        if required:
            check(ret, ok, f"Set {name}")
        print(f"Skip {name}: SDK error code {ret}")
        return False
    print(f"Set {name} = {get_double_feature(cam, name, ok):.3f}")
    return True


def set_enum_feature(cam, name, value, ok, required=False):
    if not feature_available(cam, name):
        if required:
            raise RuntimeError(f"Feature is not available: {name}")
        print(f"Skip {name}: not available")
        return False
    ret = cam.IMV_SetEnumFeatureSymbol(name, value)
    if ret != ok:
        if required:
            check(ret, ok, f"Set {name}")
        print(f"Skip {name}: SDK error code {ret}")
        return False
    print(f"Set {name} = {value}")
    return True


def print_feature_ranges(cam, ok):
    for name in ("Width", "Height", "OffsetX", "OffsetY"):
        if feature_available(cam, name):
            value = c_int64(0)
            min_value = c_int64(0)
            max_value = c_int64(0)
            inc_value = c_int64(0)
            cam.IMV_GetIntFeatureValue(name, value)
            cam.IMV_GetIntFeatureMin(name, min_value)
            cam.IMV_GetIntFeatureMax(name, max_value)
            cam.IMV_GetIntFeatureInc(name, inc_value)
            print(
                f"{name}: current={value.value}, min={min_value.value}, "
                f"max={max_value.value}, inc={inc_value.value}"
            )
    for name in ("ExposureTime", "AcquisitionFrameRate", "ResultingFrameRate"):
        if feature_available(cam, name):
            try:
                value = c_double(0.0)
                min_value = c_double(0.0)
                max_value = c_double(0.0)
                cam.IMV_GetDoubleFeatureValue(name, value)
                cam.IMV_GetDoubleFeatureMin(name, min_value)
                cam.IMV_GetDoubleFeatureMax(name, max_value)
                print(
                    f"{name}: current={value.value:.3f}, "
                    f"min={min_value.value:.3f}, max={max_value.value:.3f}"
                )
            except RuntimeError:
                pass


def enum_devices(sdk):
    device_list = sdk["IMV_DeviceList"]()
    ret = sdk["MvCamera"].IMV_EnumDevices(
        device_list,
        sdk["IMV_EInterfaceType"].interfaceTypeAll,
    )
    check(ret, sdk["IMV_OK"], "Enumerate devices")
    return device_list


def device_type_name(device_info, sdk):
    if device_info.nCameraType == sdk["typeGigeCamera"]:
        return "GigE"
    if device_info.nCameraType == sdk["typeU3vCamera"]:
        return "USB3/U3V"
    return str(device_info.nCameraType)


def text(value):
    return value.decode("utf-8", errors="ignore").strip("\x00")


def print_devices(device_list, sdk):
    if device_list.nDevNum == 0:
        print("No camera found.")
        return

    print("Index  Type      Vendor        Model              Serial")
    print("-----  --------  ------------  -----------------  ----------------")
    for i in range(device_list.nDevNum):
        info = device_list.pDevInfo[i]
        print(
            f"{i + 1:<5}  "
            f"{device_type_name(info, sdk):<8}  "
            f"{text(info.vendorName):<12}  "
            f"{text(info.modelName):<17}  "
            f"{text(info.serialNumber)}"
        )


def save_type_for(path, sdk):
    suffix = path.suffix.lower()
    if suffix == ".bmp":
        return sdk["IMV_ESaveType"].typeImageBmp
    if suffix in {".jpg", ".jpeg"}:
        return sdk["IMV_ESaveType"].typeImageJpeg
    if suffix == ".png":
        return sdk["IMV_ESaveType"].typeImagePng
    if suffix in {".tif", ".tiff"}:
        return sdk["IMV_ESaveType"].typeImageTif
    raise ValueError("Output extension must be .bmp, .jpg, .png, or .tif")


def capture_once(index, output, timeout_ms):
    sdk = load_sdk()
    device_list = enum_devices(sdk)
    if device_list.nDevNum == 0:
        raise RuntimeError("No camera found. Check USB cable, power, and driver.")
    if index < 1 or index > device_list.nDevNum:
        raise ValueError(f"Camera index must be 1..{device_list.nDevNum}")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    cam = sdk["MvCamera"]()
    frame = sdk["IMV_Frame"]()
    frame_acquired = False

    try:
        ret = cam.IMV_CreateHandle(
            sdk["IMV_ECreateHandleMode"].modeByIndex,
            byref(c_void_p(index - 1)),
        )
        check(ret, sdk["IMV_OK"], "Create camera handle")

        check(cam.IMV_Open(), sdk["IMV_OK"], "Open camera")

        # Continuous/free-run capture. Use SoftTrigger.py if you need software trigger.
        check(
            cam.IMV_SetEnumFeatureSymbol("TriggerMode", "Off"),
            sdk["IMV_OK"],
            "Set TriggerMode Off",
        )

        check(cam.IMV_StartGrabbing(), sdk["IMV_OK"], "Start grabbing")
        check(cam.IMV_GetFrame(frame, timeout_ms), sdk["IMV_OK"], "Get frame")
        frame_acquired = True

        param = sdk["IMV_SaveImageToFileParam"]()
        param.eImageType = save_type_for(output, sdk)
        param.nWidth = frame.frameInfo.width
        param.nHeight = frame.frameInfo.height
        param.nPixelFormat = frame.frameInfo.pixelFormat
        param.pSrcData = frame.pData
        param.nSrcDataLen = frame.frameInfo.size
        param.nBayerDemosaic = 2
        param.pImagePath = str(output).encode("utf-8")
        if output.suffix.lower() in {".jpg", ".jpeg"}:
            param.nQuality = 90
        elif output.suffix.lower() == ".png":
            param.nQuality = 8

        check(cam.IMV_SaveImageToFile(param), sdk["IMV_OK"], "Save image")
        print(f"Saved {output}")
        print(
            f"Frame: {frame.frameInfo.width}x{frame.frameInfo.height}, "
            f"pixelFormat={frame.frameInfo.pixelFormat}, "
            f"blockId={frame.frameInfo.blockId}"
        )
    finally:
        if frame_acquired:
            cam.IMV_ReleaseFrame(frame)
        if cam.handle:
            if cam.IMV_IsGrabbing():
                cam.IMV_StopGrabbing()
            if cam.IMV_IsOpen():
                cam.IMV_Close()
            cam.IMV_DestroyHandle()


def make_frame_path(output_dir, prefix, frame_no, suffix):
    return output_dir / f"{prefix}_{frame_no:06d}{suffix}"


def make_run_output_dir(base_dir, args):
    if args.no_save:
        return base_dir.resolve()
    if not args.timestamp_dir:
        return base_dir.resolve()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    aspect = (args.aspect or "custom").replace(":", "x")
    return (base_dir / f"{timestamp}_{aspect}").resolve()


def save_frame(cam, frame, output_path, sdk):
    param = sdk["IMV_SaveImageToFileParam"]()
    param.eImageType = save_type_for(output_path, sdk)
    param.nWidth = frame.frameInfo.width
    param.nHeight = frame.frameInfo.height
    param.nPixelFormat = frame.frameInfo.pixelFormat
    param.pSrcData = frame.pData
    param.nSrcDataLen = frame.frameInfo.size
    param.nBayerDemosaic = 2
    param.pImagePath = str(output_path).encode("utf-8")
    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        param.nQuality = 90
    elif output_path.suffix.lower() == ".png":
        param.nQuality = 8
    check(cam.IMV_SaveImageToFile(param), sdk["IMV_OK"], "Save image")


def configure_camera(cam, sdk, args):
    ok = sdk["IMV_OK"]

    set_enum_feature(cam, "TriggerMode", "Off", ok, required=True)

    if args.pixel_format:
        set_enum_feature(cam, "PixelFormat", args.pixel_format, ok)

    # Reset offsets before changing ROI; many cameras require this order.
    set_int_feature(cam, "OffsetX", 0, ok)
    set_int_feature(cam, "OffsetY", 0, ok)

    if args.width is not None:
        set_int_feature(cam, "Width", args.width, ok, required=True)
    if args.height is not None:
        set_int_feature(cam, "Height", args.height, ok, required=True)

    if args.center_roi:
        for offset_name in ("OffsetX", "OffsetY"):
            if feature_available(cam, offset_name):
                max_offset = c_int64(0)
                cam.IMV_GetIntFeatureMax(offset_name, max_offset)
                inc = get_int_feature_inc(cam, offset_name, ok)
                centered = (max_offset.value // 2 // inc) * inc if inc else max_offset.value // 2
                set_int_feature(cam, offset_name, centered, ok)

    if args.offset_x is not None:
        set_int_feature(cam, "OffsetX", args.offset_x, ok)
    if args.offset_y is not None:
        set_int_feature(cam, "OffsetY", args.offset_y, ok)

    if args.exposure_us is not None:
        set_double_feature(cam, "ExposureTime", args.exposure_us, ok)

    if args.frame_rate is not None:
        set_enum_feature(cam, "AcquisitionFrameRateEnable", "On", ok)
        set_double_feature(cam, "AcquisitionFrameRate", args.frame_rate, ok)

    print_feature_ranges(cam, ok)


def capture_burst(index, output_dir, duration_s, timeout_ms, suffix, prefix, args):
    sdk = load_sdk()
    device_list = enum_devices(sdk)
    if device_list.nDevNum == 0:
        raise RuntimeError("No camera found. Check USB cable, power, and driver.")
    if index < 1 or index > device_list.nDevNum:
        raise ValueError(f"Camera index must be 1..{device_list.nDevNum}")

    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    save_type_for(Path(f"frame{suffix}"), sdk)
    output_dir = make_run_output_dir(output_dir, args)
    output_dir.mkdir(parents=True, exist_ok=True)

    cam = sdk["MvCamera"]()
    captured = 0
    saved = 0
    first_block_id = None
    last_block_id = None
    started_at = None
    cloned_frames = []

    try:
        ret = cam.IMV_CreateHandle(
            sdk["IMV_ECreateHandleMode"].modeByIndex,
            byref(c_void_p(index - 1)),
        )
        check(ret, sdk["IMV_OK"], "Create camera handle")
        check(cam.IMV_Open(), sdk["IMV_OK"], "Open camera")

        configure_camera(cam, sdk, args)

        check(cam.IMV_StartGrabbing(), sdk["IMV_OK"], "Start grabbing")
        started_at = time.perf_counter()
        deadline = started_at + duration_s

        while time.perf_counter() < deadline:
            frame = sdk["IMV_Frame"]()
            ret = cam.IMV_GetFrame(frame, timeout_ms)
            if ret != sdk["IMV_OK"]:
                print(f"Get frame skipped, SDK error code: {ret}")
                continue

            try:
                captured += 1
                if first_block_id is None:
                    first_block_id = frame.frameInfo.blockId
                last_block_id = frame.frameInfo.blockId
                if not args.no_save:
                    if args.defer_save:
                        clone_frame = sdk["IMV_Frame"]()
                        check(cam.IMV_CloneFrame(frame, clone_frame), sdk["IMV_OK"], "Clone frame")
                        cloned_frames.append(clone_frame)
                    else:
                        output_path = make_frame_path(output_dir, prefix, captured, suffix)
                        save_frame(cam, frame, output_path, sdk)
                        saved += 1
            finally:
                cam.IMV_ReleaseFrame(frame)

        elapsed = time.perf_counter() - started_at
        fps = captured / elapsed if elapsed > 0 else 0.0
        if cloned_frames:
            if cam.IMV_IsGrabbing():
                cam.IMV_StopGrabbing()
            save_start = time.perf_counter()
            for frame_no, clone_frame in enumerate(cloned_frames, start=1):
                output_path = make_frame_path(output_dir, prefix, frame_no, suffix)
                save_frame(cam, clone_frame, output_path, sdk)
                saved += 1
            save_elapsed = time.perf_counter() - save_start
            print(f"Captured {captured} frames in {elapsed:.3f}s, capture FPS: {fps:.1f}")
            print(f"Saved {saved} cloned frames to {output_dir} in {save_elapsed:.3f}s")
        else:
            verb = "Captured" if args.no_save else "Saved"
            print(f"{verb} {captured} frames" + ("" if args.no_save else f" to {output_dir}"))
            print(f"Elapsed: {elapsed:.3f}s, effective {'capture' if args.no_save else 'saved'} FPS: {fps:.1f}")
        if first_block_id is not None:
            print(f"BlockId: {first_block_id}..{last_block_id}")
    finally:
        for clone_frame in cloned_frames:
            cam.IMV_ReleaseFrame(clone_frame)
        if cam.handle:
            if cam.IMV_IsGrabbing():
                cam.IMV_StopGrabbing()
            if cam.IMV_IsOpen():
                cam.IMV_Close()
            cam.IMV_DestroyHandle()


def main():
    parser = argparse.ArgumentParser(description="Capture one image using the IMV Python SDK.")
    parser.add_argument("--list", action="store_true", help="list connected cameras and exit")
    parser.add_argument("--index", type=int, default=DEFAULT_CAPTURE_CONFIG["index"], help="camera index from --list")
    parser.add_argument("--output", default="captures/frame.png", help="output image path")
    parser.add_argument("--burst-dir", default=DEFAULT_CAPTURE_CONFIG["burst_dir"], help="directory for burst frames")
    parser.add_argument("--duration", type=float, default=DEFAULT_CAPTURE_CONFIG["duration"], help="burst duration in seconds")
    parser.add_argument("--ext", default=DEFAULT_CAPTURE_CONFIG["ext"], help="burst image extension: .bmp, .jpg, .png, or .tif")
    parser.add_argument("--prefix", default=DEFAULT_CAPTURE_CONFIG["prefix"], help="burst frame filename prefix")
    parser.add_argument(
        "--burst",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_CAPTURE_CONFIG["burst"],
        help="capture frames continuously for --duration",
    )
    parser.add_argument("--no-save", action="store_true", help="measure capture rate without saving files")
    parser.add_argument(
        "--defer-save",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_CAPTURE_CONFIG["defer_save"],
        help="clone frames during burst and save after capture",
    )
    parser.add_argument(
        "--timestamp-dir",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_CAPTURE_CONFIG["timestamp_dir"],
        help="create one timestamp output folder for every capture run",
    )
    parser.add_argument("--width", type=int, help="ROI width in pixels")
    parser.add_argument("--height", type=int, help="ROI height in pixels")
    parser.add_argument(
        "--aspect",
        choices=tuple(ASPECT_PRESETS.keys()),
        default=DEFAULT_CAPTURE_CONFIG["aspect"],
        help="use a preset ROI size",
    )
    parser.add_argument("--center-roi", action="store_true", help="center ROI after width/height are set")
    parser.add_argument("--offset-x", type=int, help="ROI X offset in pixels")
    parser.add_argument("--offset-y", type=int, help="ROI Y offset in pixels")
    parser.add_argument("--pixel-format", default=DEFAULT_CAPTURE_CONFIG["pixel_format"], help="camera PixelFormat, e.g. Mono8")
    parser.add_argument("--exposure-us", type=float, default=DEFAULT_CAPTURE_CONFIG["exposure_us"], help="ExposureTime in microseconds")
    parser.add_argument("--frame-rate", type=float, default=DEFAULT_CAPTURE_CONFIG["frame_rate"], help="AcquisitionFrameRate if supported")
    parser.add_argument("--timeout-ms", type=int, default=1000, help="frame timeout in ms")
    args = parser.parse_args()

    if args.aspect and args.width is None and args.height is None:
        args.width, args.height = ASPECT_PRESETS[args.aspect]
        args.center_roi = True

    if args.list:
        sdk = load_sdk()
        print_devices(enum_devices(sdk), sdk)
        return

    if args.burst:
        capture_burst(
            args.index,
            Path(args.burst_dir),
            args.duration,
            args.timeout_ms,
            args.ext,
            args.prefix,
            args,
        )
        return

    capture_once(args.index, Path(args.output), args.timeout_ms)


if __name__ == "__main__":
    main()
