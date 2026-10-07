# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""The HUD ring: a monochrome radial equaliser (brief section 4).

32 log-spaced bands, mirrored (low->high, high->low) and repeated 4x = 256 bars. Bands are smoothed with an
asymmetric attack/release and interpolated between the 30 Hz frames, so the ring moves at the display rate
without stepping. Each core state blends in over ~200 ms; nothing ever snaps.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any

from PySide6.QtCore import Property, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtQuick import QQuickPaintedItem

from .spectrum_smoother import SpectrumSmoother

BANDS = 32
MODES = ("idle", "listening", "thinking", "speaking", "confirm", "offline")


class HudRing(QQuickPaintedItem):
    modeChanged = Signal()
    feedChanged = Signal()
    colorsChanged = Signal()
    bootChanged = Signal()
    flagsChanged = Signal()

    def __init__(self, parent: Any = None):
        super().__init__(parent)
        self.setAntialiasing(True)
        self.setOpaquePainting(False)
        self._mode = "idle"
        self._feed: QObject | None = None
        self._ink = QColor("#0A0A0A")
        self._faint = QColor("#C9C5BE")
        self._mid = QColor("#76736D")
        self._accent = QColor("#F96148")
        self._boot = 1.0
        self._reduced = False
        self._running = True
        self._repeats = 4
        self.mic = SpectrumSmoother(BANDS)
        self.tts = SpectrumSmoother(BANDS)
        self._w = {m: (1.0 if m == "idle" else 0.0) for m in MODES}
        self._t = 0.0
        self._last = time.perf_counter()
        self._rot = 0.0
        self._rot_speed = 0.0
        self._dash_rot = 0.0
        self._comet = 0.0
        self._impulse = 0.0
        self._shock = -1.0
        self._rms = 0.0
        self._rebuild()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _rebuild(self) -> None:
        n = BANDS * 2 * self._repeats
        self._n = n
        self._band_of = []
        for k in range(n):
            seg = k % (2 * BANDS)
            self._band_of.append(seg if seg < BANDS else 2 * BANDS - 1 - seg)
        rnd = random.Random(7)
        self._jit = [0.9 + 0.2 * rnd.random() for _ in range(n)]
        self._val = [0.0] * n
        self._peak = [0.0] * n
        self._hold = [0.0] * n

    # ------------------------------------------------------------------ properties
    def _get_mode(self) -> str:
        return self._mode

    def _set_mode(self, m: str) -> None:
        if m not in MODES:
            m = "idle"
        if m != self._mode:
            self._mode = m
            self.modeChanged.emit()

    mode = Property(str, _get_mode, _set_mode, notify=modeChanged)

    def _get_feed(self) -> QObject | None:
        return self._feed

    def _set_feed(self, f: QObject | None) -> None:
        if f is self._feed:
            return
        if self._feed is not None:
            try:
                self._feed.spectrumFrame.disconnect(self._on_frame)
            except (RuntimeError, TypeError):
                pass
        self._feed = f
        if f is not None and hasattr(f, "spectrumFrame"):
            f.spectrumFrame.connect(self._on_frame)
        self.feedChanged.emit()

    feed = Property(QObject, _get_feed, _set_feed, notify=feedChanged)

    def _color_prop(attr: str, sig: Signal):  # type: ignore[misc]
        def g(self: "HudRing") -> QColor:
            return getattr(self, attr)

        def s(self: "HudRing", c: QColor) -> None:
            setattr(self, attr, QColor(c))
            self.colorsChanged.emit()

        return Property(QColor, g, s, notify=sig)

    ink = _color_prop("_ink", colorsChanged)
    faint = _color_prop("_faint", colorsChanged)
    mid = _color_prop("_mid", colorsChanged)
    accent = _color_prop("_accent", colorsChanged)
    del _color_prop

    def _get_boot(self) -> float:
        return self._boot

    def _set_boot(self, b: float) -> None:
        self._boot = max(0.0, min(1.0, float(b)))
        self.bootChanged.emit()

    boot = Property(float, _get_boot, _set_boot, notify=bootChanged)

    def _get_reduced(self) -> bool:
        return self._reduced

    def _set_reduced(self, v: bool) -> None:
        self._reduced = bool(v)
        self.flagsChanged.emit()

    reducedMotion = Property(bool, _get_reduced, _set_reduced, notify=flagsChanged)

    def _get_running(self) -> bool:
        return self._running

    def _set_running(self, v: bool) -> None:
        self._running = bool(v)
        if self._running and not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()
        elif not self._running:
            self._timer.stop()
        self.flagsChanged.emit()

    running = Property(bool, _get_running, _set_running, notify=flagsChanged)

    def _get_repeats(self) -> int:
        return self._repeats

    def _set_repeats(self, r: int) -> None:
        r = int(r) if int(r) in (2, 4, 6) else 4
        if r != self._repeats:
            self._repeats = r
            self._rebuild()
            self.flagsChanged.emit()

    repeats = Property(int, _get_repeats, _set_repeats, notify=flagsChanged)

    # ------------------------------------------------------------------ input
    def _on_frame(self, bands: list, rms: int, clap: bool, source: str) -> None:
        (self.tts if source == "tts" else self.mic).push([b / 255.0 for b in bands], rms / 255.0)
        if clap and self._mode != "offline":
            self._shock = 0.0
            self._impulse = 0.3

    # ------------------------------------------------------------------ animation
    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.1, max(0.001, now - self._last))
        self._last = now
        self._t += dt
        self.mic.step(dt)
        self.tts.step(dt)
        rate = 1 - math.exp(-dt * (9.0 if self._reduced else 5.5))
        for m in MODES:
            self._w[m] += ((1.0 if m == self._mode else 0.0) - self._w[m]) * rate
        target_speed = 0.0 if self._reduced else 0.02 * self._w["idle"]
        self._rot_speed += (target_speed - self._rot_speed) * (1 - math.exp(-dt * 2.0))
        self._rot = (self._rot + self._rot_speed * 360 * dt) % 360
        if not self._reduced:
            self._dash_rot = (self._dash_rot - 0.012 * 360 * dt * self._w["listening"]) % 360
        self._comet = (self._comet + 0.8 * 360 * dt) % 360
        self._impulse *= math.exp(-dt * 5.0)
        if self._shock >= 0:
            self._shock += dt / 0.45
            if self._shock > 1:
                self._shock = -1.0
        mic_rms = self.mic.rms
        tts_rms = self.tts.rms
        target_rms = mic_rms * (0.35 * self._w["idle"] + self._w["listening"]) + tts_rms * self._w["speaking"]
        self._rms += (target_rms - self._rms) * (1 - math.exp(-dt * 10))
        self._compute(dt)
        self.update()

    def _compute(self, dt: float) -> None:
        w = self._w
        n = self._n
        mic, tts = self.mic.values, self.tts.values
        t = self._t
        boot = self._boot
        reveal_head = boot * 1.25 * n
        think = w["thinking"]
        comet = self._comet
        off = w["offline"]
        fall = 1.58 * dt          # 0.6 R/s over the 0.38 R bar range
        for k in range(n):
            b = self._band_of[k]
            ang = (k * 360.0 / n + self._rot) % 360
            v = 0.0
            if w["idle"] > 0.001:
                nz = 0.5 + 0.25 * math.sin(math.radians(ang) * 3 + t * 2 * math.pi / 6) + 0.25 * math.cos(math.radians(ang) * 5 - t * 2 * math.pi / 9)
                v += w["idle"] * (0.08 + 0.06 * nz + 0.35 * mic[b])
            if w["listening"] > 0.001:
                v += w["listening"] * (0.03 + 0.97 * mic[b])
            if think > 0.001:
                d = abs((ang - comet + 540) % 360 - 180)
                c = 0.5 * (1 + math.cos(math.pi * d / 20.0)) if d < 20 else 0.0
                v += think * (0.10 + 0.5 * c)
            if w["speaking"] > 0.001:
                v += w["speaking"] * (0.03 + 0.97 * tts[b])
            if w["confirm"] > 0.001:
                v += w["confirm"] * (0.20 + 0.015 * math.sin(t * 2 + k * 0.3))
            if off > 0.001:
                v += off * 0.05
            v = (v + self._impulse * (1 - off)) * self._jit[k]
            if boot < 1.0:
                v *= max(0.0, min(1.0, (reveal_head - k) / 24.0))
            v = 0.0 if v < 0 else 1.0 if v > 1 else v
            self._val[k] = v
            if v >= self._peak[k]:
                self._peak[k] = v
                self._hold[k] = 0.4
            elif self._hold[k] > 0:
                self._hold[k] -= dt
            else:
                self._peak[k] = max(v, self._peak[k] - fall)

    # ------------------------------------------------------------------ painting
    def paint(self, p: QPainter) -> None:
        side = min(self.width(), self.height())
        if side < 10:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2, self.height() / 2
        R = side / 2.5
        w = self._w
        alpha = 1.0 - 0.7 * w["offline"]
        boot = self._boot
        ink = QColor(self._ink)
        ink.setAlphaF(alpha)
        faint = QColor(self._faint)
        faint.setAlphaF(alpha * min(1.0, boot * 1.6))
        mid = QColor(self._mid)
        mid.setAlphaF(alpha * min(1.0, boot * 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)

        def circle(r: float, color: QColor, width: float) -> None:
            p.setPen(QPen(color, width))
            p.drawEllipse(QPointF(cx, cy), r, r)

        # guides
        circle(1.17 * R, faint, 1.0)
        circle(0.58 * R, ink, 1.0)
        circle(0.50 * R, faint, 0.75)
        circle(0.148 * R, faint, 1.0)
        # ticks: every 5 deg, darker every 10, long and black at the cardinals
        tick_ink = QColor(ink)
        tick_ink.setAlphaF(alpha * min(1.0, boot * 1.6))
        for i in range(72):
            a = math.radians(i * 5)
            s, c = math.sin(a), math.cos(a)
            if i % 18 == 0:
                p.setPen(QPen(tick_ink, 1.6))
                r1, r2 = 1.085 * R, 1.17 * R
            elif i % 2 == 0:
                p.setPen(QPen(mid, 1.0))
                r1, r2 = 1.105 * R, 1.148 * R
            else:
                p.setPen(QPen(faint, 1.0))
                r1, r2 = 1.122 * R, 1.142 * R
            p.drawLine(QPointF(cx + r1 * s, cy - r1 * c), QPointF(cx + r2 * s, cy - r2 * c))
        # dotted guide (rotates in listening, blinks in confirm)
        blink = w["confirm"] > 0.5 and int(self._t * 2) % 2 == 1
        if not blink:
            dot = QColor(ink)
            dot.setAlphaF(alpha * 0.85 * min(1.0, boot * 1.6))
            pen = QPen(dot, 1.25)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            circ = 2 * math.pi * 1.04 * R
            gap = circ / 300 / 1.25
            pen.setDashPattern([0.01, gap])
            pen.setDashOffset((self._dash_rot / 360.0) * circ / 1.25)
            p.setPen(pen)
            p.drawEllipse(QPointF(cx, cy), 1.04 * R, 1.04 * R)

        # bars
        n = self._n
        r0 = 0.62 * R
        lmin = 0.025 * R
        span = R - r0 - lmin
        pitch = 2 * math.pi * r0 / n
        extra = 0.3 * w["speaking"]
        wb = 0.9 * pitch / 2 + extra
        wt = 0.5 * pitch / 2 + extra
        path = QPainterPath()
        peaks = QPainterPath()
        rot = self._rot
        dot_r = max(0.9, 0.0042 * R)
        for k in range(n):
            v = self._val[k]
            a = math.radians(k * 360.0 / n + rot)
            s, c = math.sin(a), math.cos(a)
            tip = r0 + lmin * (1.0 if boot >= 1 else min(1.0, v * 40)) + v * span
            # base and tip corners (normal = (c, s) in screen coords)
            bx, by = cx + r0 * s, cy - r0 * c
            tx, ty = cx + tip * s, cy - tip * c
            path.moveTo(bx + wb * c, by + wb * s)
            path.lineTo(tx + wt * c, ty + wt * s)
            path.lineTo(tx - wt * c, ty - wt * s)
            path.lineTo(bx - wb * c, by - wb * s)
            path.closeSubpath()
            pk = self._peak[k]
            if pk > v + 0.02 and w["offline"] < 0.5:
                pr = r0 + lmin + pk * span + 0.02 * R
                peaks.addEllipse(QPointF(cx + pr * s, cy - pr * c), dot_r, dot_r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawPath(path)
        p.drawPath(peaks)

        # centre dot: breathes with the level, pulses at 1 Hz while thinking
        pulse = w["thinking"] * 0.012 * (1 + math.sin(self._t * 2 * math.pi))
        rd = R * (0.075 + 0.045 * min(1.0, self._rms * 2.2) + pulse)
        p.drawEllipse(QPointF(cx, cy), rd, rd)

        # clap shockwave
        if self._shock >= 0:
            sh = self._shock
            ease = 1 - (1 - sh) ** 3
            rr = r0 + (1.2 * R - r0) * ease
            col = QColor(ink)
            col.setAlphaF(alpha * (1 - sh) * 0.9)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(col, 1.2))
            p.drawEllipse(QPointF(cx, cy), rr, rr)

        # confirm: the only coloured element on the left panel
        if w["confirm"] > 0.02:
            acc = QColor(self._accent)
            acc.setAlphaF(min(1.0, w["confirm"]) * alpha)
            pen = QPen(acc, max(2.0, 0.011 * R))
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rr = 1.04 * R
            p.drawArc(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr), int((90 - 9) * 16), int(18 * 16))
