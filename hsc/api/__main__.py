#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Run the rig service.

    uv run python -m hsc.api --host 100.x.y.z --port 8000

Binds to the Tailscale address in production. There is no application-level
authentication: the tailnet is the security boundary, so anyone on it can fire
the injector.
"""

import argparse
from pathlib import Path

import uvicorn

from hsc.api.app import RigServices, create_app
from hsc.app_paths import data_root
from hsc.hardware.imv import ImvCamera
from hsc.rig.events import EventBus
from hsc.rig.importer import import_measure_root
from hsc.rig.jobs import JobManager, RigPaths
from hsc.rig.lease import ControlLease
from hsc.rig.store import RunStore
from hsc.rig.worker import CameraWorker


def build(data=None, spa=None, cors=()):
    """The production wiring, separated from ``main`` so it can be tested."""
    root = Path(data or data_root())
    paths = RigPaths(captures=root / "captures",
                     injections=root / "injection images",
                     measures=root / "measure")
    store = RunStore(root / "rig.db")
    import_measure_root(paths.measures, store)
    bus = EventBus()
    worker = CameraWorker(ImvCamera(), bus, paths.captures)
    return create_app(RigServices(
        store=store, jobs=JobManager(worker, store, bus, paths),
        lease=ControlLease(), bus=bus, paths=paths,
        spa_dir=Path(spa) if spa else None, cors_origins=tuple(cors)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--spa", default=None, help="built frontend directory")
    parser.add_argument("--cors", action="append", default=[],
                        help="allowed browser origin; repeatable")
    args = parser.parse_args()
    uvicorn.run(build(args.data_root, args.spa, args.cors),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
