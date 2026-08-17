#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Turn the rig's diagnostics into codes a UI can act on.

``hsc/`` raises messages written for a person -- "the piston never gets
blacker than 18 grey", "no measurable injection in this burst". Those stay as
the human fallback, but the frontend needs to branch (show the lighting
numbers, offer a recapture), so each maps to a stable code.
"""

from fastapi.responses import JSONResponse

from hsc.rig.jobs import RigBusy
from hsc.rig.lease import LeaseError

_PATTERNS = (
    ("blacker than", "CONTRAST_TOO_LOW", 422),
    ("contrast too low", "CONTRAST_TOO_LOW", 422),
    ("no measurable injection", "NO_INJECTION", 422),
    ("no piston movement", "NO_INJECTION", 422),
    ("no barrel interior", "NO_BARREL", 422),
    ("no frame timing", "NO_TIMEBASE", 422),
    ("camera is streaming", "WRONG_FRAME_SIZE", 422),
    ("no frames were grabbed", "NO_CAMERA", 503),
    ("no image frames found", "EMPTY_FOLDER", 404),
)


def to_error_code(exc):
    """``(code, http_status)`` for an exception raised by the rig layer."""
    if isinstance(exc, LeaseError):
        return "LEASE_REQUIRED", 409
    # A conflict, not a fault: the lease stops a second CLIENT driving the rig,
    # but one holder can still post two camera jobs, and two bursts on one
    # handle interleave stop/configure/start and truncate the first into a
    # plausible, quietly low peak speed. See jobs.CAMERA_KINDS.
    if isinstance(exc, RigBusy):
        return "CAMERA_BUSY", 409
    text = str(exc).lower()
    for needle, code, status in _PATTERNS:
        if needle in text:
            return code, status
    return "INTERNAL", 500


def error_response(exc):
    """The one JSON body this layer answers a failure with.

    The rig's own words are the human fallback and are never discarded: the
    code is what the UI branches on, the message is what the operator reads
    ("the piston never gets blacker than 18 grey").
    """
    code, status = to_error_code(exc)
    return JSONResponse(status_code=status,
                        content={"code": code, "message": str(exc)})


class ErrorTranslationMiddleware:
    """Answer any exception with :func:`error_response`, from INSIDE CORS.

    Deliberately a middleware rather than ``add_exception_handler(Exception,
    ...)``. Starlette diverts the ``Exception`` key to ``ServerErrorMiddleware``
    (``applications.py`` build_middleware_stack), which sits OUTSIDE
    ``CORSMiddleware`` and, after sending the response, RE-RAISES it
    (``middleware/errors.py``). Two things follow, and both were measured on
    this app with a ``sqlite3.OperationalError`` -- which is not hypothetical,
    the store behind both settings routes is SQLite:

    * uvicorn logs a full unhandled-ASGI traceback for a failure this layer
      believes it mapped;
    * the response carries no ``access-control-allow-origin``, so a browser SPA
      on the configured cross-origin cannot read the error at all -- it sees a
      CORS failure instead of the body, which is the whole reason
      ``cors_origins`` exists.

    Installed inside ``CORSMiddleware``, so the mapped response goes back out
    through it and gets the header, and nothing is re-raised.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Lifespan and WebSocket: no HTTP response exists to answer with.
            await self.app(scope, receive, send)
            return
        started = False

        async def _send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            if started:
                # The status line is already on the wire; a second one would
                # corrupt the stream. Let it reach the server, as starlette's
                # own ServerErrorMiddleware does in the same situation.
                raise
            await error_response(exc)(scope, receive, send)
