#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Reading results: runs, their per-frame CSV, and their media files.

Summary metrics live in SQLite and the per-frame series stays as the CSV each
run already wrote, so the list and detail routes read the store while the CSV
and media routes stream from the run's own folder on disk.

Wiring only. The statistics belong to :mod:`hsc.summary`, the persistence to
``RunStore`` and the folder scan to ``hsc.rig.importer`` -- this module
translates HTTP to those calls and nothing else.
"""

import math
from dataclasses import asdict
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from hsc import summary
from hsc.rig.importer import import_measure_root


def _media_file(folder, name):
    """The file *name* names inside *folder*, or refuse.

    ``name`` comes from the URL, so this is a path-traversal sink: the rig's
    database and ``settings/calibration.json`` sit one and two levels above a
    measure folder. Containment is checked on the RESOLVED paths -- a string
    prefix test would pass ``..\\..\\rig.db`` (a single URL segment, and a
    traversal on Windows) and would follow a symlink straight out of the
    folder. Anything that resolves outside is refused, never trimmed and
    retried.
    """
    candidate = Path(name)
    if candidate.is_absolute() or candidate.drive or candidate.root:
        # Absolute, UNC, and drive-relative ("C:rig.db", which resolves
        # against the process cwd): none of them can name a file in this run.
        raise HTTPException(status_code=400, detail="media name must be relative")
    target = (folder / candidate).resolve()
    if not target.is_relative_to(folder) or not target.is_file():
        raise HTTPException(status_code=404, detail="no such file")
    return target


def _json_safe(value):
    """NaN, spelled for JSON.

    ``summary.describe`` reports NaN for a metric no selected run recorded.
    JSON has no NaN and starlette encodes with ``allow_nan=False``, so passing
    it through would turn "this batch has no jet numbers" into a 500.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def register(app, services):

    def _run_or_404(run_id):
        run = services.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown run")
        return run

    # Sync handlers on purpose: the store is blocking sqlite and FileResponse
    # touches the disk, so FastAPI runs a plain ``def`` in the threadpool
    # instead of stalling the event loop that also serves the event stream.
    @app.get("/api/runs")
    def list_runs(kind: str | None = None, label: str | None = None,
                  limit: int = 100):
        return [asdict(r) for r in services.store.list_runs(kind, label, limit)]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int):
        return asdict(_run_or_404(run_id))

    @app.get("/api/runs/{run_id}/csv")
    def get_csv(run_id: int):
        run = _run_or_404(run_id)
        path = summary.find_csv(Path(run.measure_dir))
        if path is None:
            raise HTTPException(status_code=404, detail="no CSV for this run")
        # FileResponse streams the file in chunks and closes the handle; the
        # per-frame CSV of a long stroke is not something to hold in memory.
        return FileResponse(path, media_type="text/csv")

    @app.get("/api/runs/{run_id}/media/{name}")
    def get_media(run_id: int, name: str):
        run = _run_or_404(run_id)
        return FileResponse(_media_file(Path(run.measure_dir).resolve(), name))

    @app.post("/api/runs/import")
    def import_runs():
        result = import_measure_root(services.paths.measures, services.store)
        return {"imported": result.imported, "skipped": result.skipped}

    @app.post("/api/summary")
    def make_summary(body: dict):
        folders = [Path(_run_or_404(int(run_id)).measure_dir)
                   for run_id in body.get("run_ids", [])]
        try:
            result = summary.summarize(folders, services.paths.measures)
        except RuntimeError as exc:
            # The operator picked folders that carry no numbers. That is a
            # bad selection, not a rig fault, and the message names what was
            # looked for -- so it must not surface as a 500.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"path": result["path"],
                "stats": {key: {name: _json_safe(value)
                                for name, value in stat.items()}
                          for key, stat in result["stats"].items()},
                "skipped": result["skipped"]}
