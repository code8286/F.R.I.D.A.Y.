# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Wake phrase ("FRIDAY wake up") and the spoken barge-in word ("stop").

The default engine is Vosk with a grammar restricted to the configured phrases plus `[unk]`: offline, light enough to
run 24x7, no account. The engine sits behind `WakeEngine`, so Porcupine (or anything else) is a drop-in swap.

Waking is NOT authorization. Anyone's voice, or a video on your speakers, can say the phrase. A wake only opens a
listening window; it never grants a privilege and never answers an approval.

Vosk and its model are optional; they are imported and loaded only when this engine is built.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ..core.errors import FridayError
from .audio_hub import Frame

log = logging.getLogger("friday.wake")

WAKE = "wake"
STOP = "stop"


class WakeUnavailable(FridayError):
    """The wake engine cannot be built (Vosk or its model is missing)."""


def normalize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower().replace("’", "'"))


def match_phrase(text: str, phrases: list[str]) -> str | None:
    """The configured phrase that appears as a contiguous run of words in `text`, if any."""
    words = normalize(text)
    for phrase in phrases:
        want = normalize(phrase)
        n = len(want)
        if n and any(words[i : i + n] == want for i in range(len(words) - n + 1)):
            return phrase
    return None


class WakeEngine(Protocol):
    def feed(self, pcm: bytes) -> list[str]: ...    # returns [] or ["wake"] / ["stop"]


class VoskWakeEngine:
    CHUNK_BYTES = 3200       # feed Vosk 100 ms at a time; 20 ms chunks work but waste CPU

    def __init__(self, model_path: Path | str, wake_phrases: list[str], stop_phrases: list[str], *, vosk: Any = None):
        if vosk is None:
            try:
                import vosk
            except ImportError as exc:
                raise WakeUnavailable(f"the 'vosk' package is not installed. Fix:  {sys.executable} -m pip install vosk") from exc
        path = Path(model_path)
        if not path.is_dir():
            raise WakeUnavailable(f"Vosk model folder not found: {path}. Run:  friday fetch-models vosk")
        self.wake_phrases = [p for p in wake_phrases if normalize(p)]
        self.stop_phrases = [p for p in stop_phrases if normalize(p)]
        if not self.wake_phrases:
            raise WakeUnavailable("no wake phrase configured")
        try:
            vosk.SetLogLevel(-1)
        except Exception:  # noqa: BLE001
            pass
        grammar = json.dumps([*self.wake_phrases, *self.stop_phrases, "[unk]"])
        try:
            self._model = vosk.Model(str(path))
            self._rec = vosk.KaldiRecognizer(self._model, 16000, grammar)
        except Exception as exc:  # noqa: BLE001 - corrupt model, wrong version...
            raise WakeUnavailable(f"could not load the Vosk model at {path}: {exc}") from exc
        self._buf = bytearray()

    def feed(self, pcm: bytes) -> list[str]:
        self._buf += pcm
        if len(self._buf) < self.CHUNK_BYTES:
            return []
        chunk = bytes(self._buf)
        self._buf.clear()
        if self._rec.AcceptWaveform(chunk):
            text = str(json.loads(self._rec.Result()).get("text", ""))
        else:
            text = str(json.loads(self._rec.PartialResult()).get("partial", ""))
        return self._classify(text)

    def _classify(self, text: str) -> list[str]:
        if not text:
            return []
        event = WAKE if match_phrase(text, self.wake_phrases) else STOP if match_phrase(text, self.stop_phrases) else None
        if event is None:
            return []
        self._rec.Reset()        # forget the partial so one utterance fires once
        return [event]


class WakeWorker:
    """Runs a (possibly slow) engine on its own thread so clap timing and the recorder never wait for it."""

    def __init__(self, engine: WakeEngine, on_event: Callable[[str, float], None], maxsize: int = 100):
        self._engine = engine
        self._on_event = on_event
        self._q: queue.Queue[Frame | None] = queue.Queue(maxsize=maxsize)
        self._thread: threading.Thread | None = None
        self.dropped = 0
        self.failed: str | None = None
        self._on_failure: Callable[[str], None] | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="friday-wake", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout)
            self._thread = None

    def offer(self, frame: Frame) -> None:
        if self.failed:
            return
        try:
            self._q.put_nowait(frame)
        except queue.Full:       # the engine fell behind: drop the newest frame rather than block the audio thread
            self.dropped += 1

    def _run(self) -> None:
        while True:
            frame = self._q.get()
            if frame is None:
                return
            try:
                events = self._engine.feed(frame.pcm)
            except Exception as exc:  # noqa: BLE001
                self.failed = f"{type(exc).__name__}: {exc}"
                log.error("wake engine failed and is now off: %s", self.failed)
                if self._on_failure:
                    try:
                        self._on_failure(self.failed)
                    except Exception:  # noqa: BLE001
                        pass
                return
            for ev in events:
                try:
                    self._on_event(ev, frame.t)
                except Exception:  # noqa: BLE001
                    pass
