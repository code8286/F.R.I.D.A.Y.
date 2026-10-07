# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Persistent reminder scheduler (Architecture §5 alarms).

One asyncio task. Reminders live in SQLite, so they survive restarts: anything that came due while FRIDAY was off is
announced on the next start (marked ``late``). Firing a reminder only publishes ``reminder.due`` on the event bus and
writes an audit record. It never reaches the model, so a reminder's text can't act as an instruction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import tzinfo
from typing import Any

from ..core.audit import AuditLog
from ..core.bus import EventBus
from .store import ReminderStore, next_occurrence

log = logging.getLogger("friday.scheduler")

MAX_SLEEP_S = 30.0          # also bounds clock-jump (sleep/hibernate) drift
LATE_AFTER_S = 120.0        # fired this long after its due time -> flagged "late"


class Scheduler:
    def __init__(
        self,
        store: ReminderStore,
        bus: EventBus,
        audit: AuditLog,
        tz: tzinfo,
        clock: Callable[[], float] = time.time,
    ):
        self.store, self.bus, self.audit, self.tz, self._clock = store, bus, audit, tz, clock
        self._wake: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None
        self._stopping = False

    # ---- lifecycle ----
    def start(self) -> None:
        if self._task is not None:
            return
        self._wake = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="friday-scheduler")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def poke(self) -> None:
        """Call after the reminder table changes so the sleep is recomputed. Safe from any thread (tool handlers run in one)."""
        if self._wake is not None and self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._wake.set)
            except RuntimeError:        # loop already closed during shutdown
                pass

    # ---- the loop ----
    async def _run(self) -> None:
        assert self._wake is not None
        while not self._stopping:
            self._wake.clear()           # before reading the table, so a poke that arrives meanwhile is never lost
            delay = MAX_SLEEP_S
            try:
                self.fire_due()
                nxt = self.store.next_due_at()
                if nxt is not None:
                    delay = max(0.05, min(MAX_SLEEP_S, nxt - self._clock()))
            except Exception as exc:  # never let one bad row stop the scheduler
                log.error("scheduler error: %s", exc)
                delay = 5.0
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except asyncio.TimeoutError:
                pass

    def fire_due(self) -> int:
        """Fire everything due now. Returns the number fired (also callable directly, e.g. from tests)."""
        now = self._clock()
        fired = 0
        for r in self.store.due(now):
            late = now - r.due_at > LATE_AFTER_S
            nxt = next_occurrence(r.due_at, r.repeat, self.tz, now)
            self.store.mark_fired(r.id, now, nxt)
            self.audit.append("scheduler", "reminder.fired", {"id": r.id, "late": late, "repeat": r.repeat, "chars": len(r.message)})
            self.bus.publish("reminder.due", {
                "id": r.id, "message": r.message, "due_at": r.due_at, "late": late,
                "repeat": r.repeat, "next_due_at": nxt, "task_id": r.task_id,
            })
            fired += 1
        return fired
