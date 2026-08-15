#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Bring existing run folders into the database.

Runs made before this service existed -- and any made by a CLI afterwards --
appear in the web UI because this scans the measure root and reads the
summary block each run already wrote. ``hsc.summary.read_run`` does the
parsing for the five metrics it knows about, so there is one implementation
of "what a run's numbers are"; the remaining ``RunRecord`` fields
(``fps``, ``mm_per_px``, ``barrel_mm``, ...) are not in ``summary.KEYS`` and
are read straight from the same CSV's ``key,value`` summary block instead --
never guessed, never re-derived.

Idempotent: keyed on the measure folder (``RunStore.add_run`` upserts on
``measure_dir``), so it runs at every start.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from hsc import summary
from hsc.rig.store import RunRecord

#: piston_2026-08-14-14-28-09_320x120_IN37-30U
NAME = re.compile(
    r"^(?P<kind>piston|monitor)?_?"
    r"(?P<stamp>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})"
    r"(?:_(?P<roi>\d+x\d+))?"
    r"(?:_(?P<label>.+))?$")

#: Summary-block keys ``summary.read_run`` does not surface (they sit
#: outside ``summary.KEYS``) but ``measure_piston.measure_folder`` still
#: writes as raw "key,value" lines -- read directly rather than guessed.
RAW_NUMERIC_KEYS = frozenset({
    "unstable_frames", "stroke_px", "mean_speed_mm_s",
    "barrel_mm", "orifice_mm", "fluid_density", "mm_per_px", "fps",
})
RAW_TEXT_KEYS = frozenset({"scale_source", "timebase"})


@dataclass
class ImportResult:
    imported: int = 0
    skipped: list = field(default_factory=list)


def parse_folder_name(name):
    """``(kind, captured_at, roi, label)`` from a run folder name.

    A folder that doesn't carry the usual timestamp can still be imported --
    it just can't be dated or labelled from its name, so those fields fall
    back to unset rather than a guess.
    """
    match = NAME.match(name)
    if match is None:
        return "piston", None, None, None
    year, month, day, hour, minute, second = match.group("stamp").split("-")
    captured_at = f"{year}-{month}-{day}T{hour}:{minute}:{second}"
    return (match.group("kind") or "piston", captured_at,
            match.group("roi"), match.group("label"))


def _raw_summary_values(csv_path, wanted):
    """``{key: raw string}`` for summary-block lines whose key is in *wanted*.

    Per-frame rows never collide: they start with a frame file name, and the
    header/blank lines don't match any wanted key either.
    """
    found = {}
    for line in csv_path.read_text(encoding="utf-8").splitlines():
        name, _, rest = line.partition(",")
        if name in wanted:
            found[name] = rest.strip()
    return found


def _to_float(raw):
    """``None`` for an absent or unparsable value (e.g. "n/a") -- never a guess."""
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _to_int(raw):
    value = _to_float(raw)
    return None if value is None else int(value)


def import_measure_root(measure_root, store):
    """Scan *measure_root* for measured runs and upsert them into *store*."""
    result = ImportResult()
    root = Path(measure_root)
    if not root.exists():
        return result
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        csv_path = summary.find_csv(folder)
        if csv_path is None:
            result.skipped.append((folder.name, "no piston speed CSV"))
            continue
        values = summary.read_run(folder)
        kind, captured_at, roi, label = parse_folder_name(folder.name)
        raw = _raw_summary_values(csv_path, RAW_NUMERIC_KEYS | RAW_TEXT_KEYS)
        store.add_run(RunRecord(
            kind=kind, captured_at=captured_at or "", measure_dir=str(folder),
            label=label, roi=roi,
            fps=_to_float(raw.get("fps")),
            timebase=raw.get("timebase"),
            mm_per_px=_to_float(raw.get("mm_per_px")),
            scale_source=raw.get("scale_source"),
            barrel_mm=_to_float(raw.get("barrel_mm")),
            orifice_mm=_to_float(raw.get("orifice_mm")),
            density=_to_float(raw.get("fluid_density")),
            stroke_px=_to_float(raw.get("stroke_px")),
            stroke_mm=values.get("stroke_mm"),
            duration_ms=values.get("duration_ms"),
            mean_speed_mm_s=_to_float(raw.get("mean_speed_mm_s")),
            peak_speed_mm_s=values.get("peak_speed_mm_s"),
            peak_jet_speed_m_s=values.get("peak_jet_speed_m_s"),
            peak_jet_pressure_MPa=values.get("peak_jet_pressure_MPa"),
            unstable_frames=_to_int(raw.get("unstable_frames"))))
        result.imported += 1
    return result
