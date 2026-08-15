#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""SQLite persistence for measured runs, jobs and rig settings.

Summary metrics only: the per-frame series stays in the CSV each run already
writes, which is why importing the existing folders needs no translation --
``hsc.summary.read_run`` already parses exactly these fields.

``measure_dir`` is UNIQUE and inserts upsert on it, because the importer
re-scans on every start and a run must not appear twice.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT, kind TEXT NOT NULL, captured_at TEXT NOT NULL,
    source_dir TEXT, injection_dir TEXT, measure_dir TEXT NOT NULL UNIQUE,
    roi TEXT, fps REAL, exposure_us REAL, timebase TEXT,
    mm_per_px REAL, scale_source TEXT,
    barrel_mm REAL, orifice_mm REAL, density REAL,
    stroke_px REAL, stroke_mm REAL, duration_ms REAL,
    mean_speed_mm_s REAL, peak_speed_mm_s REAL,
    peak_jet_speed_m_s REAL, peak_jet_pressure_MPa REAL,
    unstable_frames INTEGER, measured_count INTEGER
);
CREATE INDEX IF NOT EXISTS runs_captured_at ON runs (captured_at DESC);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class RunRecord:
    kind: str
    captured_at: str
    measure_dir: str
    label: str | None = None
    source_dir: str | None = None
    injection_dir: str | None = None
    roi: str | None = None
    fps: float | None = None
    exposure_us: float | None = None
    timebase: str | None = None
    mm_per_px: float | None = None
    scale_source: str | None = None
    barrel_mm: float | None = None
    orifice_mm: float | None = None
    density: float | None = None
    stroke_px: float | None = None
    stroke_mm: float | None = None
    duration_ms: float | None = None
    mean_speed_mm_s: float | None = None
    peak_speed_mm_s: float | None = None
    peak_jet_speed_m_s: float | None = None
    peak_jet_pressure_MPa: float | None = None
    unstable_frames: int | None = None
    measured_count: int | None = None
    id: int | None = None


_COLUMNS = [f.name for f in fields(RunRecord) if f.name != "id"]


class RunStore:
    """Opens (and creates) the database at *db_path*."""

    def __init__(self, db_path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        """Yield a connection, committing/rolling back and always closing it.

        ``sqlite3.Connection.__exit__`` only manages the transaction, it does
        not close the connection -- without this wrapper every call site
        would leak a database handle.
        """
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add_run(self, record):
        payload = {name: getattr(record, name) for name in _COLUMNS}
        placeholders = ", ".join(f":{name}" for name in _COLUMNS)
        updates = ", ".join(f"{name}=excluded.{name}" for name in _COLUMNS)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO runs ({', '.join(_COLUMNS)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT(measure_dir) DO UPDATE SET {updates}", payload)
            row = conn.execute(
                "SELECT id FROM runs WHERE measure_dir = ?",
                (record.measure_dir,)).fetchone()
        return int(row["id"])

    def get_run(self, run_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?",
                               (run_id,)).fetchone()
        return self._record(row)

    def run_by_measure_dir(self, measure_dir):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE measure_dir = ?",
                               (str(measure_dir),)).fetchone()
        return self._record(row)

    def list_runs(self, kind=None, label=None, limit=100):
        clauses, params = [], []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if label is not None:
            clauses.append("label = ?")
            params.append(label)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM runs {where} ORDER BY captured_at DESC "
                f"LIMIT ?", params).fetchall()
        return [self._record(row) for row in rows]

    def set_setting(self, key, value):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))

    def get_settings(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    @staticmethod
    def _record(row):
        return RunRecord(**dict(row)) if row is not None else None
