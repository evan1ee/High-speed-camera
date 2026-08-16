#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""FastAPI application over the rig service.

Thin on purpose: everything it exposes is implemented and tested in
``hsc/rig/``. This layer translates HTTP to those calls and exceptions to
codes, and serves the built SPA when one is present so the rig works from a
single process.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from hsc.api.errors import to_error_code

#: Exception types translated by :func:`hsc.api.errors.to_error_code`, and the
#: base classes every rig diagnostic arrives as. Registered INDIVIDUALLY rather
#: than only as ``Exception``: Starlette routes an ``Exception`` handler to
#: ``ServerErrorMiddleware``, which sends the response and then re-raises, so a
#: mapped failure (a 409 for a lease conflict, say) would still be logged and
#: re-raised as an unhandled server error. Handlers for concrete classes go to
#: ``ExceptionMiddleware``, which simply returns the response.
TRANSLATED = (RuntimeError, ValueError, OSError)


@dataclass
class RigServices:
    store: object
    jobs: object
    lease: object
    bus: object
    paths: object
    spa_dir: Path | None = None
    cors_origins: tuple = field(default_factory=tuple)


def create_app(services):
    @asynccontextmanager
    async def lifespan(app):
        yield
        # The camera's lifetime ends here. CameraWorker opens the device once
        # and never closes it -- it cannot know when the process is finished
        # with it -- so without this the handle is held until the process dies
        # and the next one cannot open the camera. JobManager.close cancels and
        # joins the jobs first, then closes.
        services.jobs.close()

    app = FastAPI(title="High Speed Camera Rig", lifespan=lifespan)
    app.state.services = services

    if services.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=list(services.cors_origins),
            allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    async def _errors(request: Request, exc: Exception):
        code, status = to_error_code(exc)
        # The rig's own words are the human fallback and are never discarded:
        # the code is what the UI branches on, the message is what the operator
        # reads ("the piston never gets blacker than 18 grey").
        return JSONResponse(status_code=status,
                            content={"code": code, "message": str(exc)})

    for exc_type in (*TRANSLATED, Exception):
        app.add_exception_handler(exc_type, _errors)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/camera/status")
    async def camera_status():
        return {"lease_holder": services.lease.holder}

    # Sync handlers on purpose: the store is blocking sqlite, and FastAPI runs
    # a plain ``def`` in the threadpool instead of stalling the event loop that
    # also serves the event stream.
    @app.get("/api/settings")
    def get_settings():
        return services.store.get_settings()

    @app.put("/api/settings")
    def put_settings(values: dict):
        for key, value in values.items():
            services.store.set_setting(key, value)
        return services.store.get_settings()

    from hsc.api import routes_control, routes_runs, ws_events, ws_preview
    routes_runs.register(app, services)
    routes_control.register(app, services)
    ws_events.register(app, services)
    ws_preview.register(app, services)

    # Last: a mount at "/" matches every path, so it must come after the API
    # routes. Absent or not yet built is normal -- the rig is usable from the
    # API before anyone runs the frontend build.
    if services.spa_dir is not None and Path(services.spa_dir).exists():
        app.mount("/", StaticFiles(directory=str(services.spa_dir),
                                   html=True), name="spa")
    return app
