# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""In-process async pub/sub bus.

Topics are dotted strings ("confirm.requested", "turn.finished", "kill.tripped"). Subscribers use
fnmatch patterns ("confirm.*"). Every subscriber has a bounded queue; when full the *oldest* event is
dropped so a stuck UI can never block the core. `publish_threadsafe` lets sensor threads post events.
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import itertools
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

_ids = itertools.count(1)


@dataclass(frozen=True)
class Event:
    topic: str
    payload: dict[str, Any]
    ts: float = field(default_factory=time.time)
    id: int = field(default_factory=lambda: next(_ids))


class Subscription:
    def __init__(self, bus: EventBus, pattern: str, maxsize: int):
        self._bus = bus
        self.pattern = pattern
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0
        self._closed = False

    def _offer(self, event: Event) -> None:
        if self._closed:
            return
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:  # pragma: no cover
                pass
        self.queue.put_nowait(event)

    async def get(self, timeout: float | None = None) -> Event:
        if timeout is None:
            return await self.queue.get()
        return await asyncio.wait_for(self.queue.get(), timeout)

    def close(self) -> None:
        self._closed = True
        self._bus._remove(self)

    def __aiter__(self) -> AsyncIterator[Event]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[Event]:
        while not self._closed:
            yield await self.queue.get()


Callback = Callable[[Event], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        self._callbacks: list[tuple[str, Callback]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop or asyncio.get_running_loop()

    def subscribe(self, pattern: str = "*", maxsize: int = 256) -> Subscription:
        sub = Subscription(self, pattern, maxsize)
        self._subs.append(sub)
        return sub

    def on(self, pattern: str, callback: Callback) -> None:
        self._callbacks.append((pattern, callback))

    def off(self, pattern: str, callback: Callback) -> None:
        """Remove a callback registered with on(). Unknown ones are ignored."""
        with contextlib.suppress(ValueError):
            self._callbacks.remove((pattern, callback))

    def _remove(self, sub: Subscription) -> None:
        if sub in self._subs:
            self._subs.remove(sub)

    def publish(self, topic: str, payload: dict[str, Any] | None = None) -> Event:
        event = Event(topic, dict(payload or {}))
        for sub in list(self._subs):
            if fnmatch.fnmatchcase(topic, sub.pattern):
                sub._offer(event)
        for pattern, cb in list(self._callbacks):
            if fnmatch.fnmatchcase(topic, pattern):
                try:
                    result = cb(event)
                    if asyncio.iscoroutine(result):
                        asyncio.ensure_future(self._guard(result, topic))
                except Exception:  # a broken listener must never break the publisher
                    pass
        return event

    @staticmethod
    async def _guard(coro: Awaitable[None], topic: str) -> None:
        try:
            await coro
        except Exception:
            pass

    def publish_threadsafe(self, topic: str, payload: dict[str, Any] | None = None) -> None:
        if self._loop is None:
            raise RuntimeError("bus has no bound loop; call bind_loop() first")
        self._loop.call_soon_threadsafe(self.publish, topic, payload)
