#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Descriptive statistics across several measured piston runs.

One run answers "what did this injector do once"; a batch answers "what does
this injector do", which is the question a report actually asks. This reads
the summary block each run already writes into its ``*_speed.csv`` and
aggregates the five figures that characterise a shot -- stroke, peak piston
speed, duration, and the peak jet speed and pressure derived from them.

Camera-free and Tk-free: it only reads CSVs, so it is unit-testable headless
and can be run over an archive of old runs.
"""

import time
from pathlib import Path

import numpy as np


#: (key in the run CSV, column heading). The keys are exactly the ones
#: measure_piston writes into its summary block, so a run folder needs no
#: extra metadata to take part.
METRICS = (
    ("stroke_mm", "stroke_mm"),
    ("peak_speed_mm_s", "peak_speed_mm_s"),
    ("duration_ms", "duration_ms"),
    ("peak_jet_speed_m_s", "peak_jet_speed_m_s"),
    ("peak_jet_pressure_MPa", "peak_jet_pressure_MPa"),
)
KEYS = tuple(key for key, _label in METRICS)
#: Reported per metric. `cv_percent` (std/mean) is the one that says whether
#: the injector is repeatable, which is usually the point of running a batch.
STATISTICS = ("n", "mean", "std", "cv_percent", "min", "median", "max")
FILE_PREFIX = "summary"


def find_csv(folder):
    """The piston speed CSV inside a measured run folder, or None."""
    matches = sorted(Path(folder).glob("*_speed.csv"))
    return matches[0] if matches else None


def read_run(folder):
    """``{metric: value}`` from a run's CSV summary block.

    Only the ``key,value`` summary lines are read; the per-frame rows begin
    with a file name, which never matches a metric key. Missing metrics are
    simply absent -- runs measured before the jet columns existed still
    contribute their stroke and speed.
    """
    csv_path = find_csv(folder)
    if csv_path is None:
        raise RuntimeError(f"No piston speed CSV in {Path(folder).name}")
    values = {}
    for line in csv_path.read_text(encoding="utf-8").splitlines():
        parts = line.split(",")
        if len(parts) < 2 or parts[0] not in KEYS:
            continue
        try:
            value = float(parts[1])
        except ValueError:
            continue                      # "n/a" for an unmeasurable figure
        if np.isfinite(value):
            values[parts[0]] = value
    return values


def collect(folders):
    """``[(run_name, {metric: value})]`` for the folders that have a CSV.

    Returns the failures alongside, so the caller can say which folders were
    skipped instead of quietly averaging fewer runs than the operator chose.
    """
    runs, skipped = [], []
    for folder in folders:
        folder = Path(folder)
        try:
            values = read_run(folder)
        except (RuntimeError, OSError) as exc:
            skipped.append((folder.name, str(exc)))
            continue
        if values:
            runs.append((folder.name, values))
        else:
            skipped.append((folder.name, "no summary values in the CSV"))
    return runs, skipped


def describe(runs):
    """``{metric: {statistic: value}}`` across the collected runs."""
    stats = {}
    for key, _label in METRICS:
        series = np.array([v[key] for _name, v in runs if key in v], dtype=float)
        if series.size == 0:
            stats[key] = {name: float("nan") for name in STATISTICS}
            stats[key]["n"] = 0
            continue
        mean = float(np.mean(series))
        std = float(np.std(series, ddof=1)) if series.size > 1 else 0.0
        stats[key] = {
            "n": int(series.size),
            "mean": mean,
            "std": std,
            "cv_percent": (100.0 * std / mean) if mean else float("nan"),
            "min": float(np.min(series)),
            "median": float(np.median(series)),
            "max": float(np.max(series)),
        }
    return stats


def write_summary(dest_dir, runs, stats, skipped=(), stamp=None):
    """Write the per-run table and the statistics block. Returns the path."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or time.strftime("%Y-%m-%d-%H-%M-%S")
    path = dest_dir / f"{FILE_PREFIX}_{stamp}.csv"
    labels = [label for _key, label in METRICS]

    def cell(value):
        return f"{value:.4f}" if np.isfinite(value) else ""

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("run," + ",".join(labels) + "\n")
        for name, values in runs:
            fh.write(name + "," + ",".join(
                cell(values.get(key, float("nan"))) for key, _l in METRICS) + "\n")
        fh.write("\n")
        fh.write("statistic," + ",".join(labels) + "\n")
        for statistic in STATISTICS:
            row = []
            for key, _label in METRICS:
                value = stats[key][statistic]
                row.append(str(int(value)) if statistic == "n" else cell(value))
            fh.write(statistic + "," + ",".join(row) + "\n")
        if skipped:
            fh.write("\nskipped,reason\n")
            for name, reason in skipped:
                fh.write(f"{name},{reason}\n")
    return path


def summarize(folders, dest_dir):
    """Read *folders*, aggregate, and write the summary CSV.

    Returns ``{"path", "runs", "stats", "skipped"}``.
    """
    runs, skipped = collect(folders)
    if not runs:
        raise RuntimeError(
            "None of the selected folders holds a measured piston run "
            "(looking for a *_speed.csv written by Measure Piston).")
    stats = describe(runs)
    path = write_summary(dest_dir, runs, stats, skipped)
    return {"path": str(path), "runs": runs, "stats": stats, "skipped": skipped}


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", help="measured run folders")
    parser.add_argument("--dest", default=None,
                        help="where to write the summary (default: the "
                             "measure folder holding the runs)")
    args = parser.parse_args()

    dest = args.dest or Path(args.folders[0]).parent
    result = summarize(args.folders, dest)
    for name, reason in result["skipped"]:
        print(f"[skipped] {name}: {reason}")
    print(f"{len(result['runs'])} run(s) -> {result['path']}")
    for key, label in METRICS:
        s = result["stats"][key]
        print(f"  {label:24s} mean {s['mean']:10.3f}  std {s['std']:8.3f}  "
              f"cv {s['cv_percent']:5.1f}%  n={s['n']}")


if __name__ == "__main__":
    main()
