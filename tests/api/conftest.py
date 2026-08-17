#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""A real rig service stack over a fake camera, with no server anywhere.

Every fixture here is the production wiring: the same ``RunStore``,
``JobManager``, ``ControlLease`` and ``EventBus`` the rig runs on, driven
through FastAPI's in-process ``TestClient``. Nothing binds a port.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hsc.api.app import RigServices, create_app
from hsc.hardware.fake import FakeCamera
from hsc.rig.events import EventBus
from hsc.rig.jobs import JobManager, RigPaths
from hsc.rig.lease import ControlLease
from hsc.rig.store import RunStore
from hsc.rig.worker import CameraWorker

BURST = Path(__file__).resolve().parents[1] / "fixtures" / "burst_320x120"


def build_services(tmp_path, camera=None):
    """The whole rig service stack under *tmp_path*, camera included."""
    paths = RigPaths(captures=tmp_path / "captures",
                     injections=tmp_path / "injection images",
                     measures=tmp_path / "measure")
    bus = EventBus()
    store = RunStore(tmp_path / "rig.db")
    worker = CameraWorker(camera or FakeCamera(BURST), bus, paths.captures)
    return RigServices(store=store, jobs=JobManager(worker, store, bus, paths),
                       lease=ControlLease(), bus=bus, paths=paths)


@pytest.fixture
def services(tmp_path):
    return build_services(tmp_path)


@pytest.fixture
def client(services):
    return TestClient(create_app(services))
