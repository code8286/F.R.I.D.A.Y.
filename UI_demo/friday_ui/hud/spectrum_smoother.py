# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Band smoothing for the HUD ring (brief section 4.4).

Frames arrive at 30 Hz; the ring draws at the display rate. Between frames the target is interpolated, then each
band follows it with an asymmetric easing (attack 0.55, release 0.12 per 60 Hz frame, scaled to the real frame
time), so bars jump up quickly and fall slowly. A stream that stops for 250 ms eases to silence, never freezes."""

from __future__ import annotations

import time

ATTACK = 0.55
RELEASE = 0.12
FRAME_S = 1 / 30
STALE_S = 0.25


class SpectrumSmoother:
    def __init__(self, n: int):
        self.n = n
        self.values = [0.0] * n
        self._prev = [0.0] * n
        self._cur = [0.0] * n
        self._t = 0.0
        self.rms = 0.0
        self._rms_target = 0.0

    def push(self, bands: list[float], rms: float) -> None:
        if len(bands) != self.n:
            bands = (list(bands) + [0.0] * self.n)[: self.n]
        self._prev = [self._interp(i) for i in range(self.n)]
        self._cur = [max(0.0, min(1.0, float(b))) for b in bands]
        self._t = time.perf_counter()
        self._rms_target = max(0.0, min(1.0, rms))

    def _interp(self, i: int) -> float:
        a = min(1.0, (time.perf_counter() - self._t) / FRAME_S) if self._t else 1.0
        return self._prev[i] + (self._cur[i] - self._prev[i]) * a

    def step(self, dt: float) -> None:
        stale = not self._t or time.perf_counter() - self._t > STALE_S
        f = dt * 60.0
        ka = 1 - (1 - ATTACK) ** f
        kr = 1 - (1 - RELEASE) ** f
        vals = self.values
        for i in range(self.n):
            tgt = 0.0 if stale else self._interp(i)
            cur = vals[i]
            vals[i] = cur + (tgt - cur) * (ka if tgt > cur else kr)
        tr = 0.0 if stale else self._rms_target
        self.rms += (tr - self.rms) * (ka if tr > self.rms else kr)
