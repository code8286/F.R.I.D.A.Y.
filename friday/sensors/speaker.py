# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Speaking: audio playback plus the async `Speaker` that serialises speech and supports barge-in.

`Speaker.busy` is True from the moment something is queued until everything has finished playing. The voice channel
keeps the microphone's recorder OFF while it is busy (and for a short guard afterwards), so FRIDAY never transcribes
its own voice and a spoken "yes" in a reply can never be mistaken for an approval.

`Speaker.interrupt()` is thread-safe: the wake engine's spoken "stop", a clap, or the kill switch can call it from any
thread. Playback checks the stop flag every 50 ms.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.errors import FridayError
from .audio_hub import AudioDeviceError, import_sounddevice
from .tts import Audio, SpeechEngine, TTSError

log = logging.getLogger("friday.speaker")


class AudioPlayer(Protocol):
    def available(self) -> str | None: ...
    def play(self, audio: Audio, stop: threading.Event) -> bool: ...    # blocking; True if it played to the end


def resolve_output_device(sd: Any, spec: str) -> int | None:
    spec = (spec or "").strip()
    if not spec:
        return None
    if spec.isdigit():
        idx = int(spec)
        sd.query_devices(idx)
        return idx
    needle = spec.lower()
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] >= 1 and needle in dev["name"].lower():
            return idx
    raise AudioDeviceError(f"no output device matches {spec!r}; run `friday audio-devices` to list them")


class SoundDevicePlayer:
    CHUNK_S = 0.05

    def __init__(self, device_spec: str = "", *, sd: Any = None):
        self._spec = device_spec
        self._sd = sd

    def available(self) -> str | None:
        try:
            self._sd or import_sounddevice()
        except AudioDeviceError as exc:
            return str(exc)
        return None

    def play(self, audio: Audio, stop: threading.Event) -> bool:
        sd = self._sd or import_sounddevice()
        try:
            device = resolve_output_device(sd, self._spec)
            stream = sd.RawOutputStream(samplerate=audio.rate, channels=1, dtype="int16", device=device)
            stream.start()
        except Exception as exc:  # noqa: BLE001
            raise AudioDeviceError(f"cannot open the speakers: {exc}") from exc
        step = int(audio.rate * self.CHUNK_S) * 2
        try:
            for i in range(0, len(audio.pcm), step):
                if stop.is_set():
                    stream.abort()
                    return False
                stream.write(audio.pcm[i : i + step])
            if stop.is_set():
                stream.abort()
                return False
            stream.stop()               # lets the buffered tail finish playing
            return True
        except Exception as exc:  # noqa: BLE001
            raise AudioDeviceError(f"playback failed: {exc}") from exc
        finally:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass


class NullPlayer:
    """No speakers available: speech is skipped (the reply is still shown on screen)."""

    def available(self) -> str | None:
        return "no audio output is available"

    def play(self, audio: Audio, stop: threading.Event) -> bool:
        return False


@dataclass(frozen=True)
class SpeakResult:
    status: str                 # "done" | "interrupted" | "failed" | "empty"


class Speaker:
    def __init__(
        self,
        engine: SpeechEngine,
        player: AudioPlayer,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_busy: Callable[[bool], None] | None = None,
    ):
        self.engine = engine
        self.player = player
        self._clock = clock
        self._on_busy = on_busy
        self._lock: asyncio.Lock | None = None
        self._stop = threading.Event()
        self._tl = threading.Lock()
        self._epoch = 0
        self._pending = 0
        self.busy = False
        self.last_end = -1e9

    def interrupt(self) -> None:
        """Stop what is playing and cancel everything queued. Safe from any thread."""
        with self._tl:
            self._epoch += 1
            self._stop.set()

    async def say(self, text: str, *, cacheable: bool = False) -> SpeakResult:
        if not text or not text.strip():
            return SpeakResult("empty")
        if self._lock is None:
            self._lock = asyncio.Lock()
        with self._tl:
            epoch = self._epoch
        self._pending += 1
        if not self.busy:
            self.busy = True
            self._notify(True)
        try:
            async with self._lock:
                with self._tl:
                    if epoch != self._epoch:
                        return SpeakResult("interrupted")
                    self._stop.clear()
                try:
                    audio = await asyncio.to_thread(self.engine.synth, text, cacheable=cacheable)
                except TTSError as exc:
                    log.warning("speech skipped: %s", exc)
                    return SpeakResult("failed")
                except Exception as exc:  # noqa: BLE001 - a broken engine must never escape into a turn or an approval
                    log.error("speech engine crashed: %s: %s", type(exc).__name__, exc)
                    return SpeakResult("failed")
                with self._tl:
                    if epoch != self._epoch:
                        return SpeakResult("interrupted")
                try:
                    finished = await asyncio.to_thread(self.player.play, audio, self._stop)
                except FridayError as exc:
                    log.warning("playback failed: %s", exc)
                    return SpeakResult("failed")
                except Exception as exc:  # noqa: BLE001
                    log.error("playback crashed: %s: %s", type(exc).__name__, exc)
                    return SpeakResult("failed")
                return SpeakResult("done" if finished else "interrupted")
        finally:
            self._pending -= 1
            if self._pending == 0:
                self.last_end = self._clock()
                self.busy = False
                self._notify(False)

    def _notify(self, busy: bool) -> None:
        if self._on_busy:
            try:
                self._on_busy(busy)
            except Exception:  # noqa: BLE001
                pass
