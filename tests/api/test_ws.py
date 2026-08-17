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
import threading

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


@pytest.mark.parametrize("send, payload", [
    ("send_text", "{not json"),                 # JSONDecodeError
    ("send_bytes", b"\x00\x01"),                # KeyError: 'text'
])
def test_a_frame_the_event_socket_cannot_parse_is_skipped_not_fatal(
        client, send, payload):
    """One bad frame must not cost a client its whole event stream. The valid
    heartbeat that follows is answered, which is only possible if the reader
    survived the bad one."""
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        ws.receive_json()                       # hello
        getattr(ws, send)(payload)
        ws.send_json({"kind": "heartbeat"})
        reply = ws.receive_json()
    assert reply["kind"] == "lease"


def test_a_disconnect_unsubscribes_and_frees_the_rig(client, services):
    """A leaked subscriber is a slow memory leak that also slows every later
    publish, and a controller whose tab is gone must not keep the rig."""
    services.lease.claim("me")
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        ws.receive_json()                       # hello
    assert services.lease.holder is None
    assert services.bus._subscribers == []


def test_a_stale_socket_does_not_free_a_lease_a_reconnected_one_owns(client,
                                                                     services):
    """The half-open case, entered by hand because the stale socket has to die
    while the live one is still open.

    A controller's connection goes half-open; the client reconnects under the
    same id and carries on. Minutes later the OS finally tears the old socket
    down. Releasing on ``holder == client_id`` alone would free the lease the
    LIVE socket owns, and the window is however long that teardown takes.
    """
    services.lease.claim("me")
    stale = client.websocket_connect("/ws/events?client_id=me")
    stale.__enter__()
    stale.receive_json()                        # hello
    with client.websocket_connect("/ws/events?client_id=me") as live:
        live.receive_json()                     # hello
        stale.__exit__(None, None, None)        # the half-open socket dies
        assert services.lease.holder == "me"
    assert services.lease.holder is None        # the last one closing does free


def test_one_anonymous_client_closing_leaves_anothers_lease_alone(client,
                                                                  services):
    """Two tabs that never sent a client_id share the default id, so identity
    alone cannot tell whose socket just closed."""
    services.lease.claim("anonymous")
    first = client.websocket_connect("/ws/events")
    first.__enter__()
    first.receive_json()                        # hello
    with client.websocket_connect("/ws/events") as second:
        second.receive_json()                   # hello
        first.__exit__(None, None, None)
        assert services.lease.holder == "anonymous"
    assert services.lease.holder is None


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


def test_a_sequence_number_past_the_field_width_wraps_rather_than_raising():
    """seq counts every frame the rig publishes. ``struct`` raises on anything
    past 2**32 rather than wrapping, which would end a long-lived preview."""
    assert _header(pack_preview(2 ** 32 + 5, 8, 4, 0, b""))[0] == 5


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


@pytest.mark.parametrize("send, payload", [
    ("send_text", "{not json"),                 # JSONDecodeError
    ("send_bytes", b"\x00\x01"),                # KeyError: 'text'
    ("send_json", {"fps": "fast"}),             # ValueError from float()
    ("send_json", [1, 2]),                      # AttributeError: no .get
    # float() takes these; JSON cannot carry them back. NaN also made _wanted
    # False forever (both fps <= 0 and x >= 1.0/nan are False), so the viewer
    # was muted for good -- and the ack that would have said so encodes as the
    # bare token NaN, which a browser's JSON.parse rejects. Refused at ingest.
    ("send_json", {"fps": "nan"}),
    ("send_json", {"fps": "inf"}),
    ("send_json", {"fps": float("-inf")}),
])
def test_a_frame_the_preview_socket_cannot_parse_is_skipped_not_fatal(
        client, send, payload):
    with client.websocket_connect("/ws/preview") as ws:
        getattr(ws, send)(payload)
        ws.send_json({"paused": True})
        ack = ws.receive_json()
    assert ack == {"paused": True, "fps": ws_preview.DEFAULT_FPS}


def test_a_valid_fps_is_still_accepted_after_a_refused_one(client):
    """The refusal must cost the viewer the one message, not the socket."""
    with client.websocket_connect("/ws/preview") as ws:
        ws.send_json({"fps": "nan"})
        ws.send_json({"fps": 12})
        ack = ws.receive_json()
    assert ack == {"paused": False, "fps": 12.0}


def test_a_bad_fps_leaves_the_whole_control_message_unapplied(client):
    """Half-applying it would pause a viewer that asked to be paused AND
    retimed, then never acknowledge that it had -- the viewer would believe it
    was still live."""
    with client.websocket_connect("/ws/preview") as ws:
        ws.send_json({"paused": True, "fps": "fast"})
        ws.send_json({})                        # one it can parse
        ack = ws.receive_json()
    assert ack == {"paused": False, "fps": ws_preview.DEFAULT_FPS}


def test_the_jpeg_encode_runs_off_the_event_loop(client, services,
                                                 monkeypatch):
    """``cv2.imencode`` is synchronous CPU work. Run inline it owns the loop
    thread for the whole call -- releasing the GIL does not help, because the
    coroutine never yields -- and the loop it owns is the one serving
    ``/ws/events``. That is the preview-delays-events coupling the two-socket
    split exists to prevent, one layer down.

    ``pack_preview`` runs in the coroutine itself, so its thread IS the loop's:
    comparing the two is a direct read of where the encode happened.
    """
    seen = {}
    real_encode, real_pack = ws_preview.encode, ws_preview.pack_preview

    def encode(pixels, *args, **kwargs):
        seen["encode"] = threading.get_ident()
        return real_encode(pixels, *args, **kwargs)

    def pack_preview(*args, **kwargs):
        seen["loop"] = threading.get_ident()
        return real_pack(*args, **kwargs)

    monkeypatch.setattr(ws_preview, "encode", encode)
    monkeypatch.setattr(ws_preview, "pack_preview", pack_preview)
    with client.websocket_connect("/ws/preview") as ws:
        services.bus.publish("preview", timestamp=1, **FRAME)
        ws.receive_bytes()
    assert seen["encode"] != seen["loop"]


def test_a_viewer_that_asks_for_nothing_is_still_capped(client, services):
    """An uncapped default means one silent viewer encodes every frame the rig
    publishes; a browser cannot draw faster than this anyway."""
    with client.websocket_connect("/ws/preview") as ws:
        ws.send_json({})
        ack = ws.receive_json()
    assert ws_preview.DEFAULT_FPS > 0
    assert ack == {"paused": False, "fps": ws_preview.DEFAULT_FPS}


@pytest.mark.parametrize("state, sent_at, now, wanted", [
    ({"paused": False, "fps": 0.0}, 100.0, 100.0, True),    # uncapped
    ({"paused": False, "fps": 10.0}, 100.0, 100.2, True),   # interval passed
    ({"paused": False, "fps": 10.0}, 100.0, 100.05, False),  # too soon: drop
    ({"paused": True, "fps": 0.0}, 0.0, 100.0, False),      # paused: drop
    # Belt and braces on the one value that mutes a viewer permanently: with
    # NaN every other test here is False, so the frame is never wanted again.
    # _finite keeps it out of the state; if it ever gets in, send, don't mute.
    ({"paused": False, "fps": float("nan")}, 100.0, 100.0, True),
    ({"paused": True, "fps": float("nan")}, 100.0, 100.0, False),
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
