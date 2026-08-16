#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Both sockets. Events must reach observers too; preview must not stall them.

Nothing here sleeps. Every assertion is driven by an explicit publish or an
explicit client message, and read back off a real socket through
``TestClient`` -- a test that waits a while and hopes is a test that will lie
on a slow machine.
"""
import asyncio
import json
import queue
import struct

import numpy as np
import pytest

from hsc.api import ws_events, ws_preview
from hsc.api.app import create_app
from hsc.api.ws_preview import PREVIEW_HEADER, pack_preview
from hsc.rig.lease import ControlLease

from fastapi.testclient import TestClient

HEADER_SIZE = struct.calcsize(PREVIEW_HEADER)
FRAME = dict(width=8, height=4, pixels=np.zeros((4, 8), dtype=np.uint8))


def _header(payload):
    return struct.unpack(PREVIEW_HEADER, payload[:HEADER_SIZE])


class FakeClock:
    """A clock the test moves by hand, so a TTL can expire on demand."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


# -- /ws/events --------------------------------------------------------------
def test_events_socket_greets_with_role_and_lease(client):
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        hello = ws.receive_json()
    assert hello["kind"] == "hello"
    assert hello["payload"]["client_id"] == "me"
    assert hello["payload"]["lease_holder"] is None


def test_published_events_reach_a_connected_client(client, services):
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        ws.receive_json()                       # hello
        services.bus.publish("status", text="Capturing")
        message = ws.receive_json()
    assert message["kind"] == "status"
    assert message["payload"]["text"] == "Capturing"


def test_an_observer_receives_events_it_cannot_command(client, services):
    services.lease.claim("controller")
    with client.websocket_connect("/ws/events?client_id=observer") as ws:
        hello = ws.receive_json()
        assert hello["payload"]["role"] == "observer"
        services.bus.publish("log", text="line")
        assert ws.receive_json()["payload"]["text"] == "line"


def test_the_lease_holder_is_greeted_as_the_controller(client, services):
    services.lease.claim("me")
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        hello = ws.receive_json()
    assert hello["payload"]["role"] == "controller"
    assert hello["payload"]["lease_holder"] == "me"


def test_an_unnamed_client_is_an_observer(client):
    """The query parameter is optional, and a client that omits it must still
    get a well-formed greeting rather than a 500 on connect."""
    with client.websocket_connect("/ws/events") as ws:
        hello = ws.receive_json()
    assert hello["payload"]["client_id"] == "anonymous"
    assert hello["payload"]["role"] == "observer"


def test_preview_frames_never_appear_on_the_event_socket(client, services):
    """Both publishes land in the same subscriber queue in order, so receiving
    the status frame proves the preview one was dropped, not merely late."""
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        ws.receive_json()                       # hello
        services.bus.publish("preview", timestamp=1, **FRAME)
        services.bus.publish("status", text="after the frame")
        message = ws.receive_json()
    assert message["kind"] == "status"


def test_a_payload_value_json_cannot_carry_is_dropped_not_fatal(client,
                                                                services):
    """One unserialisable value must not take the whole socket down with a
    TypeError mid-send -- the rest of the event is still worth having."""
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        ws.receive_json()                       # hello
        services.bus.publish("run", id=7, pixels=np.zeros(3), note=None)
        message = ws.receive_json()
    assert message["payload"] == {"id": 7, "note": None}


def test_a_heartbeat_over_the_socket_renews_the_lease(services):
    """The socket is the client's liveness signal, so a heartbeat on it has to
    push the TTL out -- otherwise a watching controller loses the rig at 30 s
    with its browser wide open."""
    clock = FakeClock()
    services.lease = ControlLease(ttl_s=10.0, clock=clock)
    services.lease.claim("me")
    with TestClient(create_app(services)) \
            .websocket_connect("/ws/events?client_id=me") as ws:
        ws.receive_json()                       # hello
        clock.now = 8.0
        ws.send_json({"kind": "heartbeat"})
        reply = ws.receive_json()               # ack proves it was processed
        clock.now = 12.0
        assert services.lease.holder == "me"    # would have expired at 10.0
    assert reply == {"kind": "lease", "payload": {"holder": "me"}}


def test_a_heartbeat_cannot_renew_somebody_elses_lease(services):
    """A socket speaks for the client that opened it and no other, so the
    heartbeat uses the connection's own id, not one out of the message."""
    clock = FakeClock()
    services.lease = ControlLease(ttl_s=10.0, clock=clock)
    services.lease.claim("controller")
    with TestClient(create_app(services)) \
            .websocket_connect("/ws/events?client_id=observer") as ws:
        ws.receive_json()                       # hello
        clock.now = 8.0
        ws.send_json({"kind": "heartbeat", "client_id": "controller"})
        ws.receive_json()                       # ack
        clock.now = 12.0
        assert services.lease.holder is None


def test_a_disconnect_unsubscribes_and_frees_the_rig(client, services):
    """A leaked subscriber is a slow memory leak that also slows every later
    publish, and a controller whose tab is gone must not keep the rig."""
    services.lease.claim("me")
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        ws.receive_json()                       # hello
    assert services.lease.holder is None
    assert services.bus._subscribers == []


def test_a_disconnecting_observer_leaves_the_controller_alone(client,
                                                              services):
    services.lease.claim("controller")
    with client.websocket_connect("/ws/events?client_id=observer") as ws:
        ws.receive_json()                       # hello
    assert services.lease.holder == "controller"


# -- /ws/preview -------------------------------------------------------------
def test_preview_frame_packs_a_header_then_jpeg():
    payload = pack_preview(seq=7, width=320, height=120, timestamp=99,
                           jpeg=b"\xff\xd8\xff")
    size = struct.calcsize(PREVIEW_HEADER)
    seq, width, height, timestamp = struct.unpack(PREVIEW_HEADER,
                                                  payload[:size])
    assert (seq, width, height, timestamp) == (7, 320, 120, 99)
    assert payload[size:] == b"\xff\xd8\xff"


def test_a_float_timestamp_still_fits_the_integer_wire_field():
    """A publisher's clock is a float; ``struct`` will not pack one into Q."""
    assert _header(pack_preview(1, 320, 120, 12.75, b""))[3] == 12


def test_preview_socket_sends_frames_published_to_the_bus(client, services):
    import numpy as np
    with client.websocket_connect("/ws/preview") as ws:
        services.bus.publish("preview", width=8, height=4, timestamp=1,
                             pixels=np.zeros((4, 8), dtype=np.uint8))
        payload = ws.receive_bytes()
    assert len(payload) > struct.calcsize(PREVIEW_HEADER)


def test_preview_frames_carry_the_geometry_they_were_published_with(client,
                                                                    services):
    with client.websocket_connect("/ws/preview") as ws:
        services.bus.publish("preview", timestamp=42, **FRAME)
        payload = ws.receive_bytes()
    assert _header(payload) == (1, 8, 4, 42)
    assert payload[HEADER_SIZE:HEADER_SIZE + 2] == b"\xff\xd8"    # JPEG SOI


def test_the_preview_socket_ignores_everything_that_is_not_a_frame(client,
                                                                   services):
    """Job and log traffic must not reach the binary socket at all -- a client
    reading bytes cannot make sense of a JSON event."""
    with client.websocket_connect("/ws/preview") as ws:
        services.bus.publish("log", text="noise")
        services.bus.publish("preview", timestamp=5, **FRAME)
        payload = ws.receive_bytes()
    assert _header(payload) == (1, 8, 4, 5)


def test_preview_client_can_pause(client, services):
    with client.websocket_connect("/ws/preview") as ws:
        ws.send_json({"paused": True})
        ack = ws.receive_json()
    assert ack["paused"] is True


def test_preview_client_can_set_its_own_frame_rate(client, services):
    """The cap belongs to the viewer, so a slow observer throttles itself
    without slowing the controller's stream."""
    with client.websocket_connect("/ws/preview") as ws:
        ws.send_json({"fps": 5})
        ack = ws.receive_json()
    assert ack == {"paused": False, "fps": 5.0}


@pytest.mark.parametrize("state, sent_at, now, wanted", [
    ({"paused": False, "fps": 0.0}, 100.0, 100.0, True),    # uncapped
    ({"paused": False, "fps": 10.0}, 100.0, 100.2, True),   # interval passed
    ({"paused": False, "fps": 10.0}, 100.0, 100.05, False),  # too soon: drop
    ({"paused": True, "fps": 0.0}, 0.0, 100.0, False),      # paused: drop
])
def test_a_throttled_viewer_drops_the_frames_it_cannot_take(state, sent_at,
                                                            now, wanted):
    """Dropping, never queueing: a viewer that cannot keep up falls behind in
    time, not in memory, and the grab thread never learns it exists."""
    assert ws_preview._wanted(state, sent_at, now) is wanted


def test_a_preview_disconnect_unsubscribes(client, services):
    with client.websocket_connect("/ws/preview") as ws:
        services.bus.publish("preview", timestamp=1, **FRAME)
        ws.receive_bytes()
    assert services.bus._subscribers == []


def test_encoding_a_frame_produces_jpeg_bytes():
    jpeg = ws_preview.encode(np.zeros((4, 8), dtype=np.uint8))
    assert jpeg[:2] == b"\xff\xd8"


# -- the bridge from the rig's synchronous queue to the socket ---------------
@pytest.mark.parametrize("reader", [ws_events._next_event,
                                    ws_preview._next_event])
def test_a_quiet_queue_yields_nothing_rather_than_parking_the_socket(reader):
    """The reader has to come back empty-handed now and then: a thread parked
    on ``queue.get`` for ever would never notice its client had gone, and the
    subscriber it holds would leak."""
    assert asyncio.run(reader(queue.Queue(), timeout=0.001)) is None


@pytest.mark.parametrize("reader", [ws_events._next_event,
                                    ws_preview._next_event])
def test_the_reader_hands_over_an_event_that_is_already_waiting(reader):
    waiting = queue.Queue()
    waiting.put("event")
    assert asyncio.run(reader(waiting, timeout=0.001)) == "event"


def test_both_sockets_are_registered_on_the_app(client):
    """Two sockets, not one: a backed-up preview must never delay a job
    event, which is the entire reason they are separate."""
    paths = {route.path for route in client.app.routes}
    assert {"/ws/events", "/ws/preview"} <= paths


def test_the_event_frames_are_json_text(client, services):
    """Not binary JSON: the browser client reads ``event.data`` as text."""
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        message = ws.receive()
    assert json.loads(message["text"])["kind"] == "hello"
