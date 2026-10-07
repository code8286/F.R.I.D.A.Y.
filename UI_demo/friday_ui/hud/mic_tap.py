# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""`--mock-mic`: open the microphone IN THE UI, for local visual tuning only (brief section 4.6).

The core is the only microphone owner in normal use, so this refuses to start when a core is reachable. The
analysis mirrors the planned `friday/sensors/spectrum.py`: 512-sample Hann window, rfft, 32 log bands from 60 Hz
to 7.6 kHz, dB against an adaptive floor, a 48 dB range, clamped to 0..1. Only band magnitudes leave this module."""

from __future__ import annotations

import math
import queue
import socket
from typing import Any, Callable

SR = 16000
N = 512
BANDS = 32


def core_is_running(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


class MicTap:
    def __init__(self, on_frame: Callable[[list[int], int, bool], None], device: Any = None):
        import numpy as np  # noqa: F401 - checked here so the error is clear
        import sounddevice as sd  # noqa: F401

        self._on_frame = on_frame
        self._device = device
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._buf = None
        self._floor = [-70.0] * BANDS
        self._stream = None
        self._edges = None
        self._prev_rms = 0.0

    def start(self) -> None:
        import numpy as np
        import sounddevice as sd

        self._buf = np.zeros(N, dtype=np.float32)
        freqs = np.fft.rfftfreq(N, 1 / SR)
        edges = np.geomspace(60, 7600, BANDS + 1)
        self._bins = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0] for i in range(BANDS)]
        for i, b in enumerate(self._bins):     # very low bands can be narrower than one bin: use the nearest
            if len(b) == 0:
                self._bins[i] = np.array([int(np.argmin(np.abs(freqs - (edges[i] + edges[i + 1]) / 2)))])
        self._win = np.hanning(N).astype(np.float32)

        def cb(indata: Any, frames: int, t: Any, status: Any) -> None:
            self._q.put(indata[:, 0].copy())

        self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=533, device=self._device, callback=cb)
        self._stream.start()

    def poll(self) -> None:
        """Called from a Qt timer at ~30 Hz on the GUI thread."""
        import numpy as np

        got = False
        while True:
            try:
                chunk = self._q.get_nowait()
            except queue.Empty:
                break
            got = True
            self._buf = np.concatenate([self._buf, chunk])[-N:]
        if not got:
            return
        spec = np.abs(np.fft.rfft(self._buf * self._win)) ** 2
        out = []
        for i, idx in enumerate(self._bins):
            db = 10 * math.log10(float(spec[idx].mean()) + 1e-12)
            f = self._floor[i]
            self._floor[i] = f + (db - f) * (0.02 if db < f + 6 else 0.0015)
            out.append(int(max(0.0, min(1.0, (db - self._floor[i]) / 48.0)) * 255))
        rms = float(np.sqrt(np.mean(self._buf ** 2)))
        clap = rms > 0.25 and rms > 6 * max(self._prev_rms, 0.01)
        self._prev_rms = 0.9 * self._prev_rms + 0.1 * rms
        self._on_frame(out, int(min(1.0, rms * 4) * 255), clap)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
