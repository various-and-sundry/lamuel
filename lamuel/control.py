"""Shared runtime state that the web portal and the subsystems both touch.

Two small, dependency-free pieces:

* ``Switches`` -- thread-safe on/off flags for hearing, speech, and head
  tracking. The portal flips them; the subsystems read them each cycle.
* ``EventBus`` -- a fan-out of "heard"/"said" events to any connected portal
  clients, with a short history buffer so a page that connects late still sees
  the recent conversation.

Both are safe to construct even when no portal is running, so the rest of the
code can depend on them unconditionally.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque

# Event kinds carried on the bus.
HEARD = "heard"   # a transcript Lamuel took in from the microphone
SAID = "said"     # a line Lamuel spoke (or would have spoken, if muted)


class Switches:
    """Thread-safe boolean flags shared across threads.

    Every flag starts *on*. ``threading.Event`` gives us atomic set/clear/read
    without a lock of our own.
    """

    NAMES = ("conversation", "tracking")

    def __init__(self):
        self._events = {name: threading.Event() for name in self.NAMES}
        for event in self._events.values():
            event.set()

    def is_on(self, name: str) -> bool:
        return self._events[name].is_set()

    def set(self, name: str, value: bool):
        if name not in self._events:
            raise KeyError(name)
        event = self._events[name]
        event.set() if value else event.clear()

    def state(self) -> dict:
        return {name: event.is_set() for name, event in self._events.items()}


class EventBus:
    """Fan-out of conversation events to portal clients, plus recent history."""

    def __init__(self, history: int = 200):
        self._lock = threading.Lock()
        self._history: deque = deque(maxlen=history)
        self._subscribers: set[queue.Queue] = set()

    def emit(self, kind: str, text: str) -> dict:
        event = {"ts": time.time(), "kind": kind, "text": text}
        with self._lock:
            self._history.append(event)
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # a slow client shouldn't block the robot
        return event

    def subscribe(self) -> queue.Queue:
        """Register a client. The returned queue is pre-seeded with history."""
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            for event in self._history:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    break
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            self._subscribers.discard(q)
