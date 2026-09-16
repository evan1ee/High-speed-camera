#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Build a slow-motion playback video from a folder of injection frames.

The high-speed camera records thousands of frames per second; writing those
frames into a video that plays back at a normal, low frame rate turns the brief
injection event into a slow-motion clip. The video is written *into the same
folder* as the source frames (named ``<run>_slowmo.mp4``).

Pure OpenCV -- no camera/SDK needed, so it runs on any saved injection folder.
"""

import argparse
from pathlib import Path

import cv2

from hsc import injection_extract


VIDEO_FPS = 15            # playback frame rate -> lower = slower motion
VIDEO_STEM = "slowmo"


def list_frames(source_dir):
    return injection_extract.list_frames(source_dir)


def _read_bgr(path):
    """Read a frame as a 3-channel BGR image (frames are 8-bit grayscale BMP)."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is not None:
        return img
    # Fast fallback for raw 8-bit BMPs cv2 may refuse: header parse + reshape.
    info = injection_extract._bmp_info(path)
    if info is not None and info[3] == 8:
        import numpy as np
        offset, width, height, _, bottom_up = info
        data = np.fromfile(path, dtype=np.uint8)
        if data.size >= offset + width * height:
            gray = data[offset : offset + width * height].reshape(height, width)
            if bottom_up:
                gray = np.ascontiguousarray(gray[::-1])
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    raise RuntimeError(f"Cannot read image frame: {path}")


def _open_writer(base_path, size, fps):
    """Open a cv2.VideoWriter, preferring MP4 (mp4v) then falling back to AVI (MJPG)."""
    w, h = size
    for suffix, fourcc in ((".mp4", "mp4v"), (".avi", "MJPG")):
        out_path = base_path.with_suffix(suffix)
        writer = cv2.VideoWriter(
            str(out_path), cv2.VideoWriter_fourcc(*fourcc), float(fps), (w, h)
        )
        if writer.isOpened():
            return writer, out_path
        writer.release()
    raise RuntimeError(
        "Could not open a video writer (no mp4v or MJPG codec available)."
    )


def make_video(source_dir, fps=VIDEO_FPS, progress=None):
    """Write a slow-motion video of ``source_dir``'s frames into that same folder.

    Returns a dict with the output path, frame count, playback fps and size.
    """
    source_dir = Path(source_dir)
    files = list_frames(source_dir)
    if not files:
        raise RuntimeError(f"No image frames found in {source_dir}")

    first = _read_bgr(files[0])
    h, w = first.shape[:2]

    # Write the video as a single file directly inside the selected folder.
    base = source_dir / VIDEO_STEM
    writer, out_path = _open_writer(base, (w, h), fps)
    total = len(files)
    try:
        for i, path in enumerate(files, start=1):
            img = _read_bgr(path)
            if img.shape[:2] != (h, w):
                img = cv2.resize(img, (w, h))
            writer.write(img)
            if progress is not None:
                progress(i, total)
    finally:
        writer.release()

    return {
        "source_dir": str(source_dir),
        "out_path": str(out_path),
        "frame_count": total,
        "fps": int(fps),
        "size": (w, h),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="folder of injection frames")
    parser.add_argument("--fps", type=int, default=VIDEO_FPS,
                        help=f"playback fps (default {VIDEO_FPS}; lower = slower)")
    args = parser.parse_args()

    result = make_video(args.source, fps=args.fps)
    print(f"frames    : {result['frame_count']}")
    print(f"playback  : {result['fps']} fps  ({result['size'][0]}x{result['size'][1]})")
    print(f"saved to  : {result['out_path']}")


if __name__ == "__main__":
    main()
