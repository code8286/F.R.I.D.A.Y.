# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Sliding-window rate limiter (containment, Architecture §6.8)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit_per_min: int) -> bool:
        if limit_per_min <= 0:
            return True
        now = self._clock()
        q = self._hits[key]
        while q and now - q[0] >= 60.0:
            q.popleft()
        if len(q) >= limit_per_min:
            return False
        q.append(now)
        return True
