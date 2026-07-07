#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Headless build verification (no camera, no Tk) for ``--selftest``."""

from hsc import make_video
from hsc import measure_angle
from hsc.app_paths import data_root


def run_selftest(folder):
    """Headless check that a packaged build works without a camera.

    Runs the measure pipeline (cv2 / scipy / scikit-learn) and the slow-motion
    video build on an existing injection-images folder, writing the outcome to
    ``selftest.log`` next to the app (a windowed build has no console). Returns a
    process exit code (0 = passed).
    """
    import traceback

    log_path = data_root() / "selftest.log"
    lines = [f"Self-test on: {folder}"]
    code = 0
    try:
        res = measure_angle.measure_folder(
            folder, dest_base=data_root() / "selftest_out"
        )
        lines.append(
            f"MEASURE OK: {res['measured_count']} frames, "
            f"mean {res['mean_angle']:.3f} deg -> {res['dest_dir']}"
        )
        vid = make_video.make_video(folder)
        lines.append(f"VIDEO OK: {vid['frame_count']} frames -> {vid['out_path']}")
        lines.append("SELFTEST PASSED")
    except Exception:
        lines.append("SELFTEST FAILED:")
        lines.append(traceback.format_exc())
        code = 1

    text = "\n".join(lines)
    try:
        log_path.write_text(text, encoding="utf-8")
    except Exception:
        pass
    # The outcome is already in selftest.log; echo to stdout only when there is
    # one (a frozen/windowed build has sys.stdout is None).
    import sys

    if sys.stdout is not None:
        try:
            print(text)
        except Exception:
            pass
    return code
