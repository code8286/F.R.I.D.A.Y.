# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Speech-to-text with local faster-whisper (Architecture §2). Audio never leaves the machine.

`Transcriber.transcribe` is blocking (it runs the model); the voice channel calls it in a worker thread.
The model is loaded lazily on first use, from a local folder only (`local_files_only=True`): the running core never
downloads anything. `friday fetch-models whisper` is the one explicit, user-triggered download.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ..core.errors import FridayError


class SttUnavailable(FridayError):
    """Speech-to-text cannot run (faster-whisper or its model is missing)."""


class Transcriber(Protocol):
    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str: ...


class FasterWhisperTranscriber:
    NO_SPEECH_P = 0.6        # a segment this likely to be silence AND low-confidence is dropped (Whisper hallucinates on silence)
    LOW_LOGPROB = -1.0

    def __init__(
        self,
        model_path: Path | str,
        *,
        language: str = "en",
        device: str = "auto",
        compute_type: str = "int8",
        beam_size: int = 1,
        initial_prompt: str = "",
        model_factory: Callable[..., Any] | None = None,
    ):
        self.model_path = Path(model_path)
        self.language = language or None
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt or None
        self._factory = model_factory
        self._model: Any = None
        self._lock = threading.Lock()

    def check(self) -> None:
        """Cheap readiness check (does not load the model): library importable and model folder present."""
        if self._factory is None:
            try:
                import faster_whisper  # noqa: F401
            except ImportError as exc:
                raise SttUnavailable(
                    f"the 'faster-whisper' package is not installed. Fix:  {sys.executable} -m pip install faster-whisper"
                ) from exc
        if not self.model_path.is_dir() or (self._factory is None and not (self.model_path / "model.bin").is_file()):
            raise SttUnavailable(f"speech model folder not found: {self.model_path}. Run:  friday fetch-models whisper")

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                self.check()
                factory = self._factory
                if factory is None:
                    from faster_whisper import WhisperModel as factory  # noqa: N813
                try:
                    self._model = factory(str(self.model_path), device=self.device, compute_type=self.compute_type, local_files_only=True)
                except Exception as exc:  # noqa: BLE001
                    if self.device != "auto":
                        raise SttUnavailable(f"could not load the speech model at {self.model_path}: {exc}") from exc
                    try:       # "auto" may pick a GPU whose libraries are missing; the processor always works
                        self._model = factory(str(self.model_path), device="cpu", compute_type="int8", local_files_only=True)
                    except Exception as exc2:  # noqa: BLE001
                        raise SttUnavailable(f"could not load the speech model at {self.model_path}: {exc2}") from exc2
            return self._model

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        if sample_rate != 16000:
            raise ValueError("faster-whisper input must be 16 kHz")
        if len(pcm) < 3200:      # under 100 ms
            return ""
        import numpy as np

        audio = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
        model = self._load()
        segments, _info = model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
            temperature=0.0,
            initial_prompt=self.initial_prompt,
            without_timestamps=True,
        )
        parts: list[str] = []
        for seg in segments:
            if getattr(seg, "no_speech_prob", 0.0) > self.NO_SPEECH_P and getattr(seg, "avg_logprob", 0.0) < self.LOW_LOGPROB:
                continue
            parts.append(str(seg.text).strip())
        return " ".join(p for p in parts if p).strip()
