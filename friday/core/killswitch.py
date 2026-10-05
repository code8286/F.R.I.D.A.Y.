# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Global kill switch.

Tripping it (hotkey, UI button, Telegram command, or code) halts the agent immediately:
 * every running turn is cancelled,
 * the policy engine denies everything,
 * pending approvals are rejected.
Resetting requires an explicit call from a trusted principal and is audited.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from .audit import AuditLog
from .bus import EventBus
from .errors import KillSwitchTripped


class KillSwitch:
    def __init__(self, bus: EventBus | None = None, audit: AuditLog | None = None):
        self._bus = bus
        self._audit = audit
        self._tripped = threading.Event()
        self.reason: str | None = None
        self.source: str | None = None
        self._cancel_hooks: list[Callable[[], None]] = []

    @property
    def tripped(self) -> bool:
        return self._tripped.is_set()

    def check(self) -> None:
        if self._tripped.is_set():
            raise KillSwitchTripped(self.reason or "kill switch engaged")

    def on_trip(self, hook: Callable[[], None]) -> None:
        """Register a callback (e.g. cancel running turn tasks, reject pending approvals)."""
        self._cancel_hooks.append(hook)

    def trip(self, reason: str = "manual", source: str = "unknown") -> None:
        first = not self._tripped.is_set()
        self.reason, self.source = reason, source
        self._tripped.set()
        if first:
            if self._audit:
                self._audit.append(source, "kill.tripped", {"reason": reason})
            if self._bus:
                self._bus.publish("kill.tripped", {"reason": reason, "source": source})
            for hook in list(self._cancel_hooks):
                try:
                    hook()
                except Exception:
                    pass

    def reset(self, principal: str) -> None:
        if not self._tripped.is_set():
            return
        self._tripped.clear()
        self.reason = self.source = None
        if self._audit:
            self._audit.append(principal, "kill.reset", {})
        if self._bus:
            self._bus.publish("kill.reset", {"principal": principal})
