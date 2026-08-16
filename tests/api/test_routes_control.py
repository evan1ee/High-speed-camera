#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Driving the rig: lease first, then jobs."""
import threading

import pytest
from fastapi.testclient import TestClient

from hsc.api.app import create_app
from hsc.hardware.fake import FakeCamera

from .conftest import BURST, build_services

CAPTURE = dict(width=320, height=120, exposure_us=500.0, duration_s=30.0)


class GatedCamera(FakeCamera):
    """Holds the burst still inside ``grab`` until the test releases it.

    The second-camera-job test needs job A to still own the camera when job B
    is posted. Waiting for that with a sleep would be a race dressed up as a
    test, so the camera itself reports when the burst is under way and does not
    move again until the test says so.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grabbing = threading.Event()
        self.gate = threading.Event()

    def grab(self, timeout_ms):
        self.grabbing.set()
        self.gate.wait(10)
        return super().grab(timeout_ms)


@pytest.fixture(autouse=True)
def _stop_jobs(request):
    """Every job here runs on a real thread. Stop them at the end of the test
    that started them, rather than leaving a burst writing into a tmp folder
    the next test no longer knows about."""
    # Resolved at setup: a fixture cannot be fetched once teardown has begun.
    stack = (request.getfixturevalue("services")
             if "services" in request.fixturenames else None)
    yield
    if stack is not None:
        stack.jobs.close(timeout=30)


def _claim(client, client_id="me"):
    return client.post("/api/lease/claim", json={"client_id": client_id})


def test_claim_and_release(client):
    assert _claim(client).json()["holder"] == "me"
    assert client.post("/api/lease/release",
                       json={"client_id": "me"}).json()["holder"] is None


def test_second_claim_is_refused(client):
    _claim(client, "a")
    response = _claim(client, "b")
    assert response.status_code == 409
    assert response.json()["code"] == "LEASE_REQUIRED"


def test_heartbeat_from_a_non_holder_is_refused(client):
    _claim(client, "a")
    assert client.post("/api/lease/heartbeat",
                       json={"client_id": "b"}).status_code == 409


def test_heartbeat_from_the_holder_keeps_control(client):
    _claim(client)
    response = client.post("/api/lease/heartbeat", json={"client_id": "me"})
    assert response.status_code == 200
    assert response.json()["holder"] == "me"


def test_submitting_a_job_requires_the_lease(client):
    response = client.post("/api/jobs", json={
        "kind": "capture", "params": {}, "client_id": "me"})
    assert response.status_code == 409
    assert response.json()["code"] == "LEASE_REQUIRED"


def test_job_submit_get_and_cancel(client):
    _claim(client)
    submitted = client.post("/api/jobs", json={
        "kind": "capture", "client_id": "me",
        "params": {"width": 320, "height": 120, "exposure_us": 500.0,
                   "duration_s": 30.0}})
    job_id = submitted.json()["id"]
    assert client.get(f"/api/jobs/{job_id}").json()["kind"] == "capture"
    assert client.post(f"/api/jobs/{job_id}/cancel").json()["cancelled"] is True


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_cancelling_an_unknown_job_says_so(client):
    """A cancel nobody could act on reports what happened; it is not a fault
    (the job may have finished a moment earlier)."""
    assert client.post("/api/jobs/nope/cancel").json()["cancelled"] is False


def test_unknown_job_kind_is_400(client):
    _claim(client)
    response = client.post("/api/jobs", json={
        "kind": "teleport", "params": {}, "client_id": "me"})
    assert response.status_code == 400


def test_a_command_without_a_client_id_is_refused_at_the_boundary(client):
    """Who is asking is not optional on a command that drives hardware, and a
    missing or wrongly-typed field is the client's mistake -- a 422, not a 500
    from a KeyError deep in the lease."""
    assert client.post("/api/lease/claim", json={}).status_code == 422
    assert client.post("/api/lease/claim",
                       json={"client_id": 7}).status_code == 422
    assert client.post("/api/jobs", json={"client_id": "me"}).status_code == 422


def test_a_second_camera_job_is_refused_while_one_owns_the_camera(tmp_path):
    """The lease is not this guard. One holder can post two bursts, and two
    bursts on one handle interleave stop/configure/start: B's stop makes A's
    grab return None and A is written out as a quietly truncated stroke with a
    plausible, low peak speed."""
    camera = GatedCamera(BURST)
    services = build_services(tmp_path, camera)
    client = TestClient(create_app(services))
    _claim(client)
    first = client.post("/api/jobs", json={
        "kind": "capture", "client_id": "me", "params": CAPTURE})
    assert first.status_code == 200
    assert camera.grabbing.wait(10)                 # the burst is under way

    second = client.post("/api/jobs", json={
        "kind": "capture", "client_id": "me", "params": CAPTURE})
    assert second.status_code == 409
    assert second.json()["code"] == "CAMERA_BUSY"

    camera.gate.set()
    services.jobs.close(timeout=30)
