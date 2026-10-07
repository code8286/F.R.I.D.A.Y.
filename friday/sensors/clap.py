# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Double-clap detector (ported from the old jarvis.py, Architecture §2).

Same idea as before: an adaptive noise floor, a spike threshold at `spike_ratio` times that floor (never below an
absolute `min_rms`), a retrigger level the signal must fall back under, and a gap window between the two claps.

What changed:
  * No run-once-per-process limit and no hardcoded welcome actions; it only reports "a double clap happened".
  * A clap is a SHORT transient. A spike that stays loud for more than `max_spike_s` (speech, music, a door
    slam that rings on) is not counted, so talking near the microphone no longer looks like clapping.
    A clap is therefore registered when its spike ends, a few tens of milliseconds after it started.
  * The noise floor also creeps UP slowly under sustained noise, so a noisy room does not leave it pinned at its
    start-up value.
  * Time comes from the frame timestamps, not the wall clock, so detection is deterministic and testable.

The detector knows nothing about audio devices: feed it one level (RMS 0..1) per frame.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClapConfig:
    spike_ratio: float = 7.0         # how many times louder than the noise floor counts as a clap
    min_rms: float = 0.012           # never trigger below this absolute level (0..1 full scale)
    cooldown_s: float = 0.45         # minimum time between detections
    min_gap_s: float = 0.05          # shortest allowed gap between the two claps
    max_gap_s: float = 0.35          # longest allowed gap
    retrigger_ratio: float = 0.55    # level must fall below threshold * this before the spike has ended
    max_spike_s: float = 0.15        # a louder-than-threshold stretch longer than this is not a clap
    noise_alpha: float = 0.996       # floor follows quiet audio down (per 20 ms frame; ~5 s time constant)
    noise_rise_alpha: float = 0.9995 # ...and sustained noise up, ten times more slowly
    quiet_gate_mult: float = 2.2     # frames below floor * this count as "quiet" for the fast update
    warmup_s: float = 1.0            # learn the room before detecting anything


class ClapDetector:
    def __init__(self, cfg: ClapConfig | None = None):
        self.cfg = cfg or ClapConfig()
        self.noise_floor = 1e-4
        self._started: float | None = None
        self._in_spike = False
        self._spike_start = 0.0
        self._first: float | None = None
        self._last_fire = -1e9

    def reset(self) -> None:
        self._started = None
        self._in_spike = False
        self._first = None
        self._last_fire = -1e9

    @property
    def threshold(self) -> float:
        return max(self.noise_floor * self.cfg.spike_ratio, self.cfg.min_rms)

    def feed(self, level: float, t: float) -> bool:
        """One frame's RMS level at stream time `t`. Returns True when a double clap has just completed."""
        c = self.cfg
        if self._started is None:
            self._started = t
        threshold = self.threshold
        retrigger = threshold * c.retrigger_ratio

        if not self._in_spike:
            # learn the room: fast down/with quiet audio, slowly up under sustained noise
            if level < self.noise_floor * c.quiet_gate_mult:
                self.noise_floor = c.noise_alpha * self.noise_floor + (1 - c.noise_alpha) * level
            elif level < threshold:
                self.noise_floor = c.noise_rise_alpha * self.noise_floor + (1 - c.noise_rise_alpha) * level
            self.noise_floor = max(self.noise_floor, 1e-7)

        if t - self._started < c.warmup_s:
            return False

        if self._in_spike:
            if level < retrigger:                       # the spike has ended
                self._in_spike = False
                duration = t - self._spike_start
                if duration <= c.max_spike_s:
                    return self._register(self._spike_start, t)
                self._first = None                      # something long and loud: not a clap, forget any half pair
            return False

        if level >= threshold and (t - self._last_fire) >= c.cooldown_s:
            self._in_spike = True
            self._spike_start = t
        return False

    def _register(self, onset: float, now: float) -> bool:
        c = self.cfg
        if self._first is None:
            self._first = onset
            return False
        gap = onset - self._first
        if gap < c.min_gap_s:
            return False
        if gap <= c.max_gap_s:
            self._first = None
            self._last_fire = now
            return True
        self._first = onset                              # too slow: this clap starts a new pair
        return False
