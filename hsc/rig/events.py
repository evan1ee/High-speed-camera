#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""In-process fan-out of rig events.

Publishing NEVER blocks: a subscriber that stops draining loses events rather
than stalling the publisher, because the publisher is the camera grab thread
and a stalled grab loop drops frames from a running capture.
"""

import queue
import threading
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    kind: str
    payload: dict = field(default_factory=dict)


class EventBus:
    def __init__(self, maxsize=256, history=200):
        self._maxsize = maxsize
        self._subscribers = []
        self._history = deque(maxlen=history)
        self._guard = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=self._maxsize)
        with self._guard:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._guard:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, kind, **payload):
        event = Event(kind, payload)
        with self._guard:
            self._history.append(event)
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass                # see module docstring
        return event

    def history(self, limit=50):
        with self._guard:
            return list(self._history)[-int(limit):]
