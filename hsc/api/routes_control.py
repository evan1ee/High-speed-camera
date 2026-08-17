#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Driving the rig: the control lease, and the jobs it gates.

Every command that touches hardware requires the lease. A refusal is a typed
409, never a silent no-op -- an operator who thinks they started a capture and
did not is worse off than one who sees an error.

Wiring only. Who may drive belongs to :class:`hsc.rig.lease.ControlLease` and
what may run belongs to :class:`hsc.rig.jobs.JobManager`; this module turns
their answers into HTTP.
"""

from dataclasses import asdict

from fastapi import HTTPException
from pydantic import BaseModel, Field

from hsc.rig.lease import LeaseError


class ClientBody(BaseModel):
    """Who is asking. Not optional on a command that drives hardware, and
    validated here so a missing or wrongly-typed field is the client's 422
    rather than a KeyError surfacing as a 500 from inside the rig layer."""

    client_id: str


class JobBody(ClientBody):
    kind: str
    params: dict = Field(default_factory=dict)


def register(app, services):

    def _lease_state():
        return {"holder": services.lease.holder}

    def _announce():
        """Tell every watching tab who has control, so a client that lost the
        lease stops offering buttons it can no longer use."""
        services.bus.publish("lease", holder=services.lease.holder)
        return _lease_state()

    # Sync handlers on purpose, as in routes_runs: FastAPI runs a plain ``def``
    # in the threadpool, so the locks these take and the thread ``submit``
    # starts never stall the event loop that also serves the event stream.
    @app.post("/api/lease/claim")
    def claim(body: ClientBody):
        if not services.lease.claim(body.client_id):
            raise LeaseError(f"rig control is held by {services.lease.holder}")
        return _announce()

    @app.post("/api/lease/release")
    def release(body: ClientBody):
        # A release by a client that no longer holds the lease is not an error:
        # a lease that expired while a laptop was shut is exactly the case, and
        # the truthful current holder is the useful answer either way.
        services.lease.release(body.client_id)
        return _announce()

    @app.post("/api/lease/heartbeat")
    def heartbeat(body: ClientBody):
        if not services.lease.heartbeat(body.client_id):
            raise LeaseError("rig control is held by another client")
        return _lease_state()

    @app.post("/api/jobs")
    def submit(body: JobBody):
        # Two guards, and they are not the same guard: ``require`` stops a
        # second CLIENT driving the rig (409 LEASE_REQUIRED), while submit's
        # own RigBusy stops one holder starting a second camera job (409
        # CAMERA_BUSY). Both are translated by hsc.api.errors.
        services.lease.require(body.client_id)
        try:
            job_id = services.jobs.submit(body.kind, body.params)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": job_id}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = services.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return asdict(job)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, body: ClientBody):
        # Lease-gated like submit, and for the same reason: cancel sets the
        # flag the grab loop reads, so it ends the burst MID-STROKE and
        # destroys the run. A stale tab must not be able to do that to the
        # holder's capture. A holder who has gone away is already handled below
        # this layer -- the lease's TTL frees it, and ``handover`` transfers it
        # deliberately -- so no ungated route is needed to stop a runaway burst.
        services.lease.require(body.client_id)
        return {"cancelled": services.jobs.cancel(job_id)}
