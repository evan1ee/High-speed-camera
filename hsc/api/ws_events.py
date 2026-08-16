#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""JSON event socket.

EVERY client receives every event, controller or observer -- watching a
capture is not a privilege. Only commands are lease-gated, and those go over
HTTP where a refusal can carry a status code.

Nothing here may slow the publisher down. :meth:`hsc.rig.events.EventBus.publish`
runs on the camera's grab thread -- up to ~1798 times a second -- and keeps that
promise by dropping into a bounded queue and swallowing ``queue.Full``. This
module only ever *reads* that queue, from a worker thread, so a client stuck on
a slow link fills its own queue and loses events; the grab loop never learns it
exists.

Kept apart from :mod:`hsc.api.ws_preview` on purpose: a backed-up preview must
not delay a job event.
"""

import asyncio
import contextlib
import queue
import threading
from collections import Counter

from fastapi import WebSocket, WebSocketDisconnect

#: How long a read parks a worker thread before coming up for air. It does NOT
#: delay events -- a waiting ``get`` returns the moment one arrives -- it bounds
#: how long a socket takes to notice its client has gone, because a read
#: already running cannot be cancelled and the cleanup below waits for it.
#: Short enough that a dropped client is unsubscribed promptly, long enough
#: that an idle socket costs 20 thread hand-offs a second and nothing else.
POLL_S = 0.05


def register(app, services):
    # How many event sockets each client_id has open. The lease is released
    # when the LAST of them closes, never on the first.
    #
    # Identity alone is not enough to say whose socket just closed. A
    # controller whose connection goes half-open reconnects under the same id
    # and carries on; when the OS finally tears the old socket down -- minutes
    # later, not POLL_S later -- ``holder == client_id`` is still true, and
    # releasing there would free the lease the LIVE socket owns. Two tabs
    # sharing the default id have the same problem.
    #
    # Guarded because the count and the release decision must be one step: a
    # socket opening between another's decrement and its holder check would
    # otherwise still lose the lease.
    live = Counter()
    guard = threading.Lock()

    def _opened(client_id):
        with guard:
            live[client_id] += 1

    def _closed(client_id):
        """Register a socket closing; True when it was the id's last one."""
        with guard:
            live[client_id] -= 1
            if live[client_id]:
                return False
            del live[client_id]          # keep the tally bounded
            return True

    @app.websocket("/ws/events")
    async def events(ws: WebSocket, client_id: str = "anonymous"):
        await ws.accept()
        # Subscribe BEFORE greeting: sending the greeting is an await, and an
        # event published during it would fall in the gap. Queued early is
        # harmless -- the send loop below only starts after the greeting -- but
        # a capture that started in that window and was never announced leaves
        # the tab showing an idle rig.
        events_q = services.bus.subscribe()
        _opened(client_id)
        # Nested, one block per resource, so a client that vanishes during the
        # greeting cannot leave the subscription behind: a leaked subscriber is
        # a slow memory leak that also lengthens every later publish, and
        # publishing is work done on the grab thread.
        try:
            # One suppression over both sends: a client can drop during the
            # greeting just as well as mid-stream, and neither is a server
            # fault worth a traceback in the log.
            with contextlib.suppress(WebSocketDisconnect):
                holder = services.lease.holder
                # The lease holder IS the camera's status as this API defines
                # it; ``/api/camera/status`` answers with the same value.
                await ws.send_json({"kind": "hello", "payload": {
                    "client_id": client_id, "lease_holder": holder,
                    "role": "controller" if holder == client_id
                            else "observer"}})
                # Started after the greeting, so its reply to a heartbeat can
                # never overtake the hello frame. It is also the disconnect
                # detector: sending is the one thing that cannot notice a
                # client has gone, so the receive side ends the send loop.
                reader = asyncio.create_task(
                    _client_messages(ws, services, client_id))
                try:
                    while not reader.done():
                        event = await _next_event(events_q)
                        if event is None or event.kind == "preview":
                            continue      # binary, on the other socket
                        await ws.send_json({"kind": event.kind,
                                            "payload": _plain(event.payload)})
                finally:
                    reader.cancel()
        finally:
            services.bus.unsubscribe(events_q)
            if _closed(client_id) and services.lease.holder == client_id:
                services.lease.release(client_id)


async def _client_messages(ws, services, client_id):
    """Read this client's heartbeats until it goes away.

    Any message from the socket is a heartbeat -- it is the only thing a client
    says here -- and it renews the lease of *this* connection's client, never
    of an id named in the message, so one tab cannot hold the rig open for
    another.
    """
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await ws.receive_json()
            services.lease.heartbeat(client_id)
            await ws.send_json({"kind": "lease",
                                "payload": {"holder": services.lease.holder}})


async def _next_event(events_q, timeout=POLL_S):
    """One event off the rig's synchronous queue, or ``None`` if none came.

    The wait happens on a worker thread, never on the event loop: a blocking
    ``get`` here would stall every other socket in the process. It times out so
    that a thread reading for a client that has already gone is released
    instead of parking for ever.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, events_q.get, True, timeout)
    except queue.Empty:
        return None


def _plain(payload):
    """The part of a payload JSON can carry.

    A rig payload is built by the rig layer, which is free to put a numpy array
    or a Path in one. Dropping those keeps one odd value from killing the whole
    socket with a ``TypeError`` in the middle of a send.
    """
    return {k: v for k, v in payload.items() if _jsonable(v)}


def _jsonable(value):
    return isinstance(value, (str, int, float, bool, list, dict, type(None)))
