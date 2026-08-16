#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Binary preview socket.

Separate from the event socket so a viewer on a slow link drops frames without
ever delaying the progress of a running capture.

The frame never travels as JSON: a base64 image inside an event would tie the
two streams together and inflate every frame by a third. A fixed 16-byte header
in front of the JPEG is enough for a browser to draw it, and its sequence
number lets a viewer see for itself how many frames it missed.

Dropping is the load policy, everywhere. The rig's bus already drops for a
subscriber that stops draining, and a client that asks for a frame cap gets its
extra frames dropped here rather than queued -- a viewer that cannot keep up
must fall behind in time, not in memory.
"""

import asyncio
import contextlib
import queue
import struct
import time

import cv2
from fastapi import WebSocket, WebSocketDisconnect

#: sequence, width, height, timestamp
PREVIEW_HEADER = "<IHHQ"

#: Low enough that a frame is small on a phone's link, high enough that the
#: piston edge the operator is aiming at is still visible.
JPEG_QUALITY = 80

#: See ws_events.POLL_S -- same bridge, same reason.
POLL_S = 0.05

#: The cap a viewer gets before it asks for one. Not zero: a viewer that never
#: sends a control message would otherwise have every published frame encoded
#: on its behalf, and no browser redraws a preview faster than this. A client
#: that genuinely wants every frame can still ask for ``fps: 0``.
DEFAULT_FPS = 30.0


def pack_preview(seq, width, height, timestamp, jpeg):
    """The wire frame: fixed header, then the JPEG.

    The fields are coerced because a publisher's clock is a float and the wire
    field is an integer -- ``struct`` will not pack one into the other.
    """
    return struct.pack(PREVIEW_HEADER, int(seq), int(width), int(height),
                       int(timestamp)) + jpeg


def encode(pixels, quality=JPEG_QUALITY):
    ok, buffer = cv2.imencode(".jpg", pixels,
                              [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buffer.tobytes() if ok else b""


def register(app, services):

    @app.websocket("/ws/preview")
    async def preview(ws: WebSocket):
        # No lease check: watching is not commanding. An observer with the
        # preview open is exactly the intended use.
        await ws.accept()
        frames_q = services.bus.subscribe()
        state = {"paused": False, "fps": DEFAULT_FPS}
        seq, sent_at = 0, 0.0
        loop = asyncio.get_running_loop()
        # As on the event socket, the receive side is what notices a client has
        # gone; here it also carries that client's own throttle.
        reader = asyncio.create_task(_client_control(ws, state))
        try:
            with contextlib.suppress(WebSocketDisconnect):
                while not reader.done():
                    event = await _next_event(frames_q)
                    if event is None or event.kind != "preview":
                        continue          # JSON, on the other socket
                    # Counted before the throttle, so the gaps in what a viewer
                    # receives tell it exactly what it missed.
                    seq += 1
                    now = time.monotonic()
                    if _wanted(state, sent_at, now):
                        sent_at = now
                        # Off the loop: ``cv2.imencode`` is synchronous CPU
                        # work, and run inline it owns the loop thread for the
                        # whole call -- the coroutine never yields, so
                        # releasing the GIL buys nothing. That loop also serves
                        # /ws/events, so encoding on it would rebuild the very
                        # preview-delays-events coupling these two separate
                        # sockets exist to prevent.
                        jpeg = await loop.run_in_executor(
                            None, encode, event.payload["pixels"])
                        await ws.send_bytes(pack_preview(
                            seq, event.payload["width"],
                            event.payload["height"],
                            event.payload["timestamp"], jpeg))
        finally:
            services.bus.unsubscribe(frames_q)
            reader.cancel()


def _wanted(state, sent_at, now):
    """Whether this viewer wants the frame that just arrived.

    A paused viewer wants none. One that asked for a frame rate wants the next
    only once its interval has passed; the rest are dropped here, so its own
    slowness never reaches the capture.
    """
    if state["paused"]:
        return False
    fps = state["fps"]
    return fps <= 0 or (now - sent_at) >= 1.0 / fps


async def _client_control(ws, state):
    """Read this viewer's throttle until it goes away.

    The reply is the whole state, not an acknowledgement of the one field that
    changed: a client that sends ``fps`` alone still learns whether it is
    paused, and there is only ever one answer to compare against.
    """
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            message = await ws.receive_json()
            state["paused"] = bool(message.get("paused", state["paused"]))
            state["fps"] = float(message.get("fps", state["fps"]))
            await ws.send_json(dict(state))


async def _next_event(frames_q, timeout=POLL_S):
    """One event off the rig's synchronous queue, or ``None`` if none came.

    Deliberately a copy of the one in :mod:`hsc.api.ws_events` rather than a
    shared bridge: two short socket handlers that each read their own queue are
    easier to reason about than one generic one, and this is the seam where
    "the grab thread must never block" is kept.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, frames_q.get, True, timeout)
    except queue.Empty:
        return None
