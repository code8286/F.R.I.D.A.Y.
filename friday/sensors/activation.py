# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Activation fusion (Architecture §2): the double clap and the wake phrase open a voice session.

Modes:  "either" (default: any one trigger opens a session)  |  "both" (a clap AND the phrase within a short window)
        |  "clap" (clap only)  |  "wake" (phrase only)
A debounce stops one event from firing twice (a clap that the wake engine also hears, or a double trigger).

Triggers come from audio threads, so `trigger` is thread-safe. The callback runs outside the lock.
Activation is not authorization: the callback only opens a listening window.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

MODES = ("either", "both", "clap", "wake")


class ActivationFusion:
    def __init__(
        self,
        mode: str,
        on_activate: Callable[[tuple[str, ...]], None],
        *,
        debounce_s: float = 3.0,
        both_window_s: float = 4.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if mode not in MODES:
            raise ValueError(f"activation mode must be one of {MODES}")
        self.mode = mode
        self._on_activate = on_activate
        self.debounce_s = debounce_s
        self.both_window_s = both_window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._last_fire = -1e9
        self._seen: dict[str, float] = {}

    def trigger(self, source: str) -> bool:
        """Report a trigger ("clap" or "wake"). Returns True if it opened (or re-opened) a session."""
        now = self._clock()
        with self._lock:
            if self.mode in ("clap", "wake") and source != self.mode:
                return False
            if now - self._last_fire < self.debounce_s:
                return False
            if self.mode == "both":
                self._seen[source] = now
                fresh = {s for s, t in self._seen.items() if now - t <= self.both_window_s}
                if not {"clap", "wake"} <= fresh:
                    return False
                sources = ("clap", "wake")
                self._seen.clear()
            else:
                sources = (source,)
            self._last_fire = now
        self._on_activate(sources)
        return True
