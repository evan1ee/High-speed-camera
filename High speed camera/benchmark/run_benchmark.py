"""Sweep the failure conditions, score the current pipeline, write a CSV.

Usage:  uv run python -m benchmark.run_benchmark <tag>
Writes: benchmark/results/<tag>.csv  (one row per case, plus a summary row)

Two suites:
  single : make_wedge -> measure_frame(bg=None)  (estimator accuracy)
  seq    : make_sequence -> BMPs in a temp dir -> measure_folder  (pipeline)
"""
import csv
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from hsc import measure_angle as ma
from benchmark.synthetic import make_wedge, make_sequence
from benchmark.score import score_frame

SINGLE_CASES = [
    # (name, half_angle, blur, noise, skirt, brightness)
    ("sharp",        3.0, 0.7,  2.0, 0.0, 230),
    ("blurry",       3.0, 2.0,  3.0, 0.0, 230),
    ("noisy",        3.0, 1.0,  8.0, 0.0, 230),
    ("skirt_mild",   3.0, 1.0,  3.0, 2.0, 230),
    ("skirt_heavy",  3.0, 1.0,  3.0, 4.0, 230),
    ("thin_narrow",  1.0, 0.8,  3.0, 0.0, 230),
    ("faint",        3.0, 1.0,  3.0, 2.0, 120),
    ("worst",        1.5, 1.5,  6.0, 3.0, 150),
]
SEQ_CASES = [
    # (name, residual_level, skirt, n_pre, n_jet)
    ("seq_clean",    0,  0.0, 18, 12),
    ("seq_residual", 60, 2.0, 18, 12),  # static residual streak in the bg
    # Steady jet dominating the temporal median (the real rig's failure mode:
    # subtraction erases the jet). Legacy cannot measure this at all (sentinel
    # 99); a pre-onset background makes it measurable.
    ("seq_steady",   60, 2.0, 10, 20),
]
SEEDS = (0, 1, 2)


def run(tag):
    rows = []
    for name, ha, blur, noise, skirt, bright in SINGLE_CASES:
        for seed in SEEDS:
            img, truth = make_wedge(ha, blur, noise, skirt, bright, seed=seed)
            res = ma.measure_frame(img, bg=None,
                                   start_x=truth["x_lo"], end_x=truth["x_hi"])
            if res is None:
                rows.append({"suite": "single", "case": name, "seed": seed,
                             "ang_err_up": 99.0, "ang_err_lo": 99.0,
                             "dist_up": 99.0, "dist_lo": 99.0})
                continue
            rows.append({"suite": "single", "case": name, "seed": seed,
                         **score_frame(res, truth)})
    # A nozzle reference saved on this machine would make measure_folder report
    # the angle vs the centerline instead of edge-to-edge, corrupting the
    # comparison against the true wedge angle -- disable it for the seq suite.
    old_load_reference = ma.reference_lines.load_reference
    ma.reference_lines.load_reference = lambda: None
    try:
        for name, residual, skirt, n_pre, n_jet in SEQ_CASES:
            frames, truth = make_sequence(n_pre=n_pre, n_jet=n_jet,
                                          residual_level=residual,
                                          skirt_scale=skirt, seed=0)
            with tempfile.TemporaryDirectory() as td:
                src = Path(td) / "run"
                src.mkdir()
                for i, f in enumerate(frames):
                    cv2.imwrite(str(src / f"frame_{i:06d}.bmp"), f)
                (src / "injection_meta.json").write_text(json.dumps(
                    {"pre_frames": n_pre, "onset_index": n_pre, "copy_start": 0,
                     "copy_end": len(frames) - 1, "method": "synthetic"}))
                try:
                    out = ma.measure_folder(src, dest_base=Path(td) / "measure",
                                            start=3, end=10,
                                            start_x=truth["x_lo"], end_x=truth["x_hi"])
                except RuntimeError:
                    # No measurable jet (e.g. the steady jet leaked fully into
                    # the window median): worst-possible sentinel scores.
                    rows.append({"suite": "seq", "case": name, "seed": 0,
                                 "ang_err_up": 99.0, "ang_err_lo": 99.0,
                                 "dist_up": 99.0, "dist_lo": 99.0})
                    continue
                # Rescore each measured frame against the truth via a re-measure of
                # the mean: use the folder's per-frame results indirectly through
                # the returned mean angle vs the true full angle.
                true_angle = abs(np.degrees(np.arctan(truth["k_up"]))
                                 - np.degrees(np.arctan(truth["k_lo"])))
                rows.append({"suite": "seq", "case": name, "seed": 0,
                             "ang_err_up": abs(out["mean_angle"] - true_angle),
                             "ang_err_lo": abs(out["mean_angle"] - true_angle),
                             "dist_up": out["angle_std"], "dist_lo": out["angle_std"]})
    finally:
        ma.reference_lines.load_reference = old_load_reference
    dest = Path(__file__).parent / "results"
    dest.mkdir(exist_ok=True)
    out_path = dest / f"{tag}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["suite", "case", "seed",
                                           "ang_err_up", "ang_err_lo",
                                           "dist_up", "dist_lo"])
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v)
                        for k, v in r.items()})
        worst = max(max(r["ang_err_up"], r["ang_err_lo"]) for r in rows)
        mean = np.mean([[r["ang_err_up"], r["ang_err_lo"]] for r in rows])
        w.writerow({"suite": "summary", "case": "mean_ang_err", "seed": "",
                    "ang_err_up": f"{mean:.4f}", "ang_err_lo": "",
                    "dist_up": f"{worst:.4f}", "dist_lo": "worst"})
    print(f"wrote {out_path}")
    return out_path


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "run")
