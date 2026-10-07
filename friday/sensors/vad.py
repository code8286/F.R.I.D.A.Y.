# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Energy-based voice activity detection and utterance endpointing.

After a voice session opens, the recorder watches frame levels, starts an utterance when speech-level energy
persists for a few frames, keeps a short pre-roll so the first syllable is not clipped, and ends the utterance
after a stretch of silence (or a hard length cap). The result is one block of PCM for the speech-to-text engine.

Deliberately simple and dependency-free: it adapts to the room's noise floor the same way the clap detector does.
Whether the audio is *speech* is decided by the transcriber; this only decides where an utterance starts and ends.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from .audio_hub import FRAME_MS, FRAME_S, Frame


@dataclass
class VadConfig:
    start_ratio: float = 3.0         # speech starts when level >= noise floor * this (and >= min_rms)...
    min_rms: float = 0.008           # ...never below this absolute level
    stop_ratio: float = 1.8          # speech continues while level >= noise floor * this (hysteresis)
    start_frames: int = 3            # consecutive loud frames to start (60 ms)
    silence_ms: int = 700            # this much quiet ends the utterance
    preroll_ms: int = 300            # audio kept from before the start was detected
    min_speech_ms: int = 250         # shorter bursts (a cough, a door) are discarded
    max_utterance_s: float = 15.0    # hard cap
    noise_alpha: float = 0.996
    noise_rise_alpha: float = 0.9995


@dataclass(frozen=True)
class Utterance:
    pcm: bytes
    start_t: float
    end_t: float
    reason: str          # "silence" | "max"


class Endpointer:
    def __init__(self, cfg: VadConfig | None = None):
        self.cfg = cfg or VadConfig()
        self.noise_floor = 1e-3
        # pre-roll is measured before the FIRST loud frame, so keep `start_frames` extra frames (the ones that triggered the start)
        self._preroll: deque[Frame] = deque(maxlen=max(1, self.cfg.preroll_ms // FRAME_MS) + self.cfg.start_frames)
        self._loud = 0
        self._speech = False
        self._buf: list[bytes] = []
        self._start_t = 0.0
        self._silence = 0
        self._voiced = 0
        self._levels: list[float] = []
        self._lock = threading.Lock()      # feed() runs on the audio thread, reset() on the event loop

    def reset(self) -> None:
        """Drop any partial utterance (the noise floor is kept)."""
        with self._lock:
            self._reset()

    def _reset(self) -> None:
        self._preroll.clear()
        self._loud = 0
        self._speech = False
        self._buf = []
        self._silence = 0
        self._voiced = 0
        self._levels = []

    @property
    def in_speech(self) -> bool:
        return self._speech

    def feed(self, frame: Frame) -> Utterance | None:
        with self._lock:
            return self._feed(frame)

    def _feed(self, frame: Frame) -> Utterance | None:
        c = self.cfg
        level = frame.level
        start_th = max(self.noise_floor * c.start_ratio, c.min_rms)
        stop_th = max(self.noise_floor * c.stop_ratio, c.min_rms * 0.6)

        if not self._speech:
            if level < start_th:
                self.noise_floor = max(
                    1e-6,
                    (c.noise_alpha * self.noise_floor + (1 - c.noise_alpha) * level)
                    if level < self.noise_floor * 2.2
                    else (c.noise_rise_alpha * self.noise_floor + (1 - c.noise_rise_alpha) * level),
                )
            self._preroll.append(frame)
            self._loud = self._loud + 1 if level >= start_th else 0
            if self._loud >= c.start_frames:
                self._speech = True
                self._buf = [f.pcm for f in self._preroll]
                self._start_t = self._preroll[0].t
                self._silence = 0
                self._voiced = self._loud
                self._levels = [f.level for f in self._preroll]
                self._preroll.clear()
            return None

        self._buf.append(frame.pcm)
        self._levels.append(level)
        if level >= stop_th:
            self._silence = 0
            self._voiced += 1
        else:
            self._silence += 1
        n = len(self._buf)
        if self._silence * FRAME_MS >= c.silence_ms:
            return self._finish(frame.t, "silence")
        if n * FRAME_S >= c.max_utterance_s:
            return self._finish(frame.t, "max")
        return None

    def _finish(self, end_t: float, reason: str) -> Utterance | None:
        voiced_ms = self._voiced * FRAME_MS
        pcm = b"".join(self._buf)
        start_t = self._start_t
        if reason == "max":
            # 15 s without a pause is usually steady noise (a fan, a TV) that sits above the threshold, not speech. Raise the
            # floor to what the quietest tenth of it looked like so it stops re-triggering; it decays again within seconds.
            lv = sorted(self._levels)
            if lv:
                self.noise_floor = max(self.noise_floor, lv[len(lv) // 10] / 2.0)
        self._reset()
        if voiced_ms < self.cfg.min_speech_ms:
            return None
        return Utterance(pcm, start_t, end_t, reason)
