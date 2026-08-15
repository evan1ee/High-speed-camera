#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Single-controller lease over the rig.

The camera is one piece of hardware and a browser invites a second tab, so
control is explicit: one client holds it, everyone else observes. A holder that
goes away without releasing (closed laptop, dropped tailnet) must not lock the
rig, hence the TTL -- the client heartbeats while it wants control.

Lives in the rig layer, not the API layer, so it is testable without a server.
``clock`` is injectable for the same reason.
"""

import threading
import time


class LeaseError(RuntimeError):
    """A control command from a client that does not hold the lease."""


class ControlLease:
    def __init__(self, ttl_s=30.0, clock=time.monotonic):
        self._ttl = float(ttl_s)
        self._clock = clock
        self._holder = None
        self._expires = 0.0
        self._guard = threading.Lock()

    @property
    def holder(self):
        with self._guard:
            return self._live_holder()

    def _live_holder(self):
        if self._holder is not None and self._clock() >= self._expires:
            self._holder = None
        return self._holder

    def claim(self, client_id):
        with self._guard:
            current = self._live_holder()
            if current is not None and current != client_id:
                return False
            self._holder = client_id
            self._expires = self._clock() + self._ttl
            return True

    def release(self, client_id):
        with self._guard:
            if self._live_holder() != client_id:
                return False
            self._holder = None
            return True

    def heartbeat(self, client_id):
        with self._guard:
            if self._live_holder() != client_id:
                return False
            self._expires = self._clock() + self._ttl
            return True

    def handover(self, from_id, to_id):
        with self._guard:
            if self._live_holder() != from_id:
                return False
            self._holder = to_id
            self._expires = self._clock() + self._ttl
            return True

    def require(self, client_id):
        """Raise unless *client_id* holds the lease."""
        current = self.holder
        if current is None:
            raise LeaseError(
                "this command needs rig control, but no client holds it -- "
                "claim control first")
        if current != client_id:
            raise LeaseError(
                f"this command needs rig control, which is held by {current}")
