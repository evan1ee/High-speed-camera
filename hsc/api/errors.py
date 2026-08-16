#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Turn the rig's diagnostics into codes a UI can act on.

``hsc/`` raises messages written for a person -- "the piston never gets
blacker than 18 grey", "no measurable injection in this burst". Those stay as
the human fallback, but the frontend needs to branch (show the lighting
numbers, offer a recapture), so each maps to a stable code.
"""

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
