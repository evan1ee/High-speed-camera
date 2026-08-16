#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""App wiring: health, settings, CORS, SPA mount, error translation, shutdown."""
import pytest
from fastapi.testclient import TestClient

from hsc.api.app import create_app
from hsc.api.deps import services_of
from hsc.api.errors import to_error_code
from hsc.hardware.fake import FakeCamera
from hsc.rig.jobs import RigBusy
from hsc.rig.lease import LeaseError

from .conftest import BURST, build_services

CAPTURE = dict(width=320, height=120, exposure_us=500.0, duration_s=5.0)


class RecordingCamera(FakeCamera):
    """A fake camera that counts how often it was closed."""

    def __init__(self, source_dir):
        super().__init__(source_dir)
        self.closes = 0

    def close(self):
        self.closes += 1
        super().close()


class RaisingStore:
    """Stands in for the store when the question is what the app does with a
    failure that reaches it."""

    def __init__(self, exc):
        self._exc = exc

    def get_settings(self):
        raise self._exc


def test_health_reports_ok(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_settings_round_trip(client):
    assert client.get("/api/settings").json() == {}
    client.put("/api/settings", json={"roi": "320x120", "exposure_us": "500"})
    assert client.get("/api/settings").json()["roi"] == "320x120"


def test_camera_status_reports_the_lease(client, services):
    body = client.get("/api/camera/status").json()
    assert body["lease_holder"] is None
    services.lease.claim("someone")
    assert client.get("/api/camera/status").json()["lease_holder"] == "someone"


@pytest.mark.xfail(reason="Task 13 adds POST /api/jobs")
def test_lease_error_maps_to_409(client, services):
    services.lease.claim("other")
    response = client.post("/api/jobs", json={
        "kind": "capture", "params": {}, "client_id": "me"})
    assert response.status_code == 409
    assert response.json()["code"] == "LEASE_REQUIRED"


def test_error_codes_carry_the_diagnostic_text():
    code, status = to_error_code(RuntimeError(
        "The piston never gets blacker than 18 grey (needs <= 10)."))
    assert code == "CONTRAST_TOO_LOW"
    assert status == 422
    assert to_error_code(RuntimeError("No measurable injection in this burst"))[0] == "NO_INJECTION"
    assert to_error_code(LeaseError("x"))[0] == "LEASE_REQUIRED"
    assert to_error_code(RuntimeError("something else"))[0] == "INTERNAL"


def test_a_second_camera_job_is_reported_as_a_conflict():
    """One lease holder can still post two bursts, and two bursts on one handle
    truncate the first -- so ``RigBusy`` is a conflict, not a server fault."""
    assert to_error_code(RigBusy("the camera is busy with job abc (capture)")) \
        == ("CAMERA_BUSY", 409)


def test_a_rig_diagnostic_keeps_its_message(services):
    services.store = RaisingStore(
        RuntimeError("No measurable injection in this burst"))
    response = TestClient(create_app(services)).get("/api/settings")
    assert response.status_code == 422
    assert response.json() == {
        "code": "NO_INJECTION",
        "message": "No measurable injection in this burst"}


def test_an_unmapped_failure_is_json_not_a_traceback(services):
    services.store = RaisingStore(KeyError("roi"))
    client = TestClient(create_app(services), raise_server_exceptions=False)
    response = client.get("/api/settings")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL"
    assert "roi" in response.json()["message"]


def test_a_malformed_body_still_gets_fastapis_own_validation_error(client):
    """Pydantic's ValidationError IS a ValueError, so the broad handler
    registration must not swallow request validation and report it as a rig
    diagnostic."""
    response = client.put("/api/settings", json=[1, 2])
    assert response.status_code == 422
    assert "detail" in response.json()


def test_cors_headers_are_present_for_a_configured_origin(services):
    services.cors_origins = ("https://rig.vercel.app",)
    client = TestClient(create_app(services))
    response = client.get("/api/health",
                          headers={"Origin": "https://rig.vercel.app"})
    assert response.headers["access-control-allow-origin"] == \
        "https://rig.vercel.app"


def test_spa_is_served_when_a_build_exists(tmp_path, services):
    spa = tmp_path / "dist"
    spa.mkdir()
    (spa / "index.html").write_text("<html>rig</html>", encoding="utf-8")
    services.spa_dir = spa
    client = TestClient(create_app(services))
    assert "rig" in client.get("/").text


def test_missing_spa_directory_is_not_fatal(client):
    assert client.get("/api/health").status_code == 200


def test_an_unbuilt_spa_directory_is_not_fatal(tmp_path, services):
    """The API has to serve the rig before anyone has run the frontend build."""
    services.spa_dir = tmp_path / "never-built"
    client = TestClient(create_app(services))
    assert client.get("/api/health").status_code == 200


def test_services_are_reachable_from_the_app(services):
    assert services_of(create_app(services)) is services


def test_shutdown_releases_the_camera(tmp_path):
    """``CameraWorker`` never closes the device -- it cannot know when the
    process is done with it -- so if this layer does not, the next process
    cannot open the camera."""
    camera = RecordingCamera(BURST)
    services = build_services(tmp_path, camera)
    # The worker opens the device on its first burst, so a capture has to have
    # run for "released" to mean anything.
    job = services.jobs.wait(services.jobs.submit("capture", CAPTURE),
                             timeout=120)
    assert job.state == "done", job.error
    assert camera.closes == 0

    with TestClient(create_app(services)):
        pass

    assert camera.closes == 1
