# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Audio hub: ONE owner of the microphone, fanning 20 ms frames out to every detector (Architecture §2).

A single input stream feeds the clap detector, the wake-phrase engine and the voice-session recorder, so they
never fight over the device (the standalone stream in the old jarvis.py is gone). Audio is 16 kHz, mono,
16-bit little-endian PCM. Frames are never written to disk or logged.

The hub is built for 24x7 use: if the device disappears, goes silent or the stream errors (unplugged mic,
sleep/wake, driver reset) it closes the stream and retries every few seconds, and reports the state change once.

The device is behind the small `AudioSource` interface so everything above it is testable without hardware.
Only `MicSource` touches `sounddevice` (optional dependency, imported lazily).
"""

from __future__ import annotations

import array
import logging
import math
import queue
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.errors import FridayError

log = logging.getLogger("friday.audio")

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000      # 320
FRAME_BYTES = FRAME_SAMPLES * 2                     # 640
FRAME_S = FRAME_MS / 1000.0


class AudioDeviceError(FridayError):
    """The microphone or speaker cannot be used (missing library, no device, device failed)."""


def rms_level(pcm: bytes) -> float:
    """RMS of 16-bit LE PCM, normalised to 0..1 (full scale = 1.0)."""
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    a = array.array("h")
    a.frombytes(pcm[: n * 2])
    if sys.byteorder == "big":  # pragma: no cover
        a.byteswap()
    return math.sqrt(sum(x * x for x in a) / n) / 32768.0


@dataclass(frozen=True)
class Frame:
    pcm: bytes
    t: float          # stream time in seconds (sample-counter based, so gaps between frames are exact)
    level: float      # RMS 0..1, computed once here so no consumer recomputes it


class AudioSource(Protocol):
    def open(self) -> None: ...
    def read(self, timeout: float) -> bytes | None: ...   # a chunk of PCM, or None on timeout
    def close(self) -> None: ...


FrameConsumer = Callable[[Frame], None]
HubEvent = Callable[[str, str], None]   # (kind, message): kind is "error" | "recovered"


class AudioHub:
    def __init__(
        self,
        source_factory: Callable[[], AudioSource],
        *,
        on_event: HubEvent | None = None,
        retry_s: float = 5.0,
        stall_s: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._factory = source_factory
        self._on_event = on_event
        self.retry_s = retry_s
        self.stall_s = stall_s
        self._clock = clock
        self._consumers: list[tuple[str, FrameConsumer]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = "stopped"          # stopped | running | retrying
        self.last_error: str | None = None
        self.frames = 0
        self._reported_error: str | None = None
        self._consumer_errors: dict[str, int] = {}

    # ---- consumers ----
    def subscribe(self, name: str, fn: FrameConsumer) -> None:
        with self._lock:
            self._consumers.append((name, fn))

    def unsubscribe(self, name: str) -> None:
        with self._lock:
            self._consumers = [c for c in self._consumers if c[0] != name]

    # ---- lifecycle ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="friday-audio-hub", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout)
        self._thread = None
        self.state = "stopped"

    # ---- the capture thread ----
    def _run(self) -> None:
        buf = bytearray()
        while not self._stop.is_set():
            src: AudioSource | None = None
            try:
                src = self._factory()
                src.open()
            except Exception as exc:  # noqa: BLE001 - any device failure means "retry later"
                self._failed(exc)
                self._close(src)
                if self._stop.wait(self.retry_s):
                    break
                continue
            self._recovered()
            buf.clear()
            stream_t = self._clock()
            last_audio = self._clock()
            try:
                while not self._stop.is_set():
                    chunk = src.read(0.5)
                    if chunk is None:
                        if self._clock() - last_audio > self.stall_s:
                            raise AudioDeviceError(f"no audio for {self.stall_s:.0f}s (device stalled or unplugged)")
                        continue
                    last_audio = self._clock()
                    buf += chunk
                    while len(buf) >= FRAME_BYTES:
                        pcm = bytes(buf[:FRAME_BYTES])
                        del buf[:FRAME_BYTES]
                        self._dispatch(Frame(pcm, stream_t, rms_level(pcm)))
                        stream_t += FRAME_S
            except Exception as exc:  # noqa: BLE001
                self._failed(exc)
            finally:
                self._close(src)
            if self._stop.wait(self.retry_s if self.state == "retrying" else 0.0):
                break
        self.state = "stopped"

    def _dispatch(self, frame: Frame) -> None:
        self.frames += 1
        with self._lock:
            consumers = list(self._consumers)
        for name, fn in consumers:
            try:
                fn(frame)
            except Exception as exc:  # noqa: BLE001 - one broken detector must not stop the others
                n = self._consumer_errors.get(name, 0) + 1
                self._consumer_errors[name] = n
                if n in (1, 10, 100):
                    log.warning("audio consumer %r failed (%d time(s)): %s: %s", name, n, type(exc).__name__, exc)

    @staticmethod
    def _close(src: AudioSource | None) -> None:
        if src is not None:
            try:
                src.close()
            except Exception:  # noqa: BLE001
                pass

    def _failed(self, exc: BaseException) -> None:
        msg = f"{type(exc).__name__}: {exc}"
        self.state = "retrying"
        self.last_error = msg
        if msg != self._reported_error:       # report each distinct failure once, not every retry
            self._reported_error = msg
            log.warning("microphone unavailable: %s (retrying every %.0fs)", msg, self.retry_s)
            self._emit("error", msg)

    def _recovered(self) -> None:
        was = self._reported_error
        self.state = "running"
        self._reported_error = None
        if was is not None:
            log.info("microphone is back")
            self._emit("recovered", "microphone is back")

    def _emit(self, kind: str, message: str) -> None:
        if self._on_event:
            try:
                self._on_event(kind, message)
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- real microphone
def import_sounddevice() -> Any:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioDeviceError(
            f"the 'sounddevice' package is not installed. Fix:  {sys.executable} -m pip install sounddevice"
        ) from exc
    except OSError as exc:  # PortAudio shared library missing (Linux)
        raise AudioDeviceError(f"PortAudio is not available ({exc}); on Linux install libportaudio2") from exc
    return sd


def input_devices(sd: Any) -> list[tuple[int, dict]]:
    return [(i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] >= 1]


def resolve_input_device(sd: Any, spec: str) -> int | None:
    """'' -> None (use the default); digits -> that index; otherwise a case-insensitive name substring."""
    spec = (spec or "").strip()
    if not spec:
        return None
    if spec.isdigit():
        idx = int(spec)
        sd.query_devices(idx)       # raises if it does not exist
        return idx
    needle = spec.lower()
    for idx, dev in input_devices(sd):
        if needle in dev["name"].lower():
            return idx
    raise AudioDeviceError(f"no input device matches {spec!r}; run `friday audio-devices` to list them")


def probe_peak_level(sd: Any, device: int | None, seconds: float = 0.5) -> float | None:
    """Peak frame RMS from a short capture, or None if the device cannot be opened at 16 kHz."""
    try:
        with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES, device=device) as stream:
            peak = 0.0
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                data, _overflow = stream.read(FRAME_SAMPLES)
                peak = max(peak, rms_level(bytes(data)))
            return peak
    except Exception:  # noqa: BLE001 - PortAudioError and friends
        return None


SILENT_RMS = 0.001


# loopback / mix inputs capture what the speakers play (including FRIDAY's own voice), never what you say
_NOT_A_MICROPHONE = ("stereo mix", "what u hear", "what you hear", "loopback", "monitor of", "wave out")


def pick_input_device(sd: Any, spec: str) -> int | None:
    """The configured device if any; else the default, and if the default is silent or unopenable, the loudest working input
    (the same fallback the old jarvis.py used)."""
    configured = resolve_input_device(sd, spec)
    if configured is not None:
        return configured
    default = None
    try:
        d = sd.default.device[0]
        default = d if d is not None and d >= 0 else None
    except Exception:  # noqa: BLE001
        default = None
    peak = probe_peak_level(sd, default)
    if peak is not None and peak >= SILENT_RMS:
        return default
    best, best_peak = None, -1.0
    for idx, dev in input_devices(sd):
        if idx == default or any(w in str(dev.get("name", "")).lower() for w in _NOT_A_MICROPHONE):
            continue
        p = probe_peak_level(sd, idx)
        if p is not None and p > best_peak:
            best, best_peak = idx, p
    if best is not None and best_peak >= SILENT_RMS:
        log.info("default microphone is silent; using input device %d instead", best)
        return best
    return default


class MicSource:
    """Default-microphone capture via a PortAudio callback. The callback only enqueues bytes (it must never block)."""

    MAX_QUEUED_CHUNKS = 250       # ~5 s; beyond that the consumer is stalled, so drop rather than grow without bound

    def __init__(self, device_spec: str = "", *, sd: Any = None):
        self._spec = device_spec
        self._sd = sd
        self._q: queue.SimpleQueue[bytes] = queue.SimpleQueue()
        self._stream: Any = None
        self._device: int | None = None
        self._picked = False
        self.dropped = 0

    def open(self) -> None:
        sd = self._sd or import_sounddevice()
        if not self._picked:
            self._device = pick_input_device(sd, self._spec)
            self._picked = True
        q = self._q

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            if q.qsize() >= self.MAX_QUEUED_CHUNKS:
                self.dropped += 1
                return
            q.put(bytes(indata))

        try:
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES, device=self._device, callback=callback
            )
            self._stream.start()
        except Exception as exc:  # noqa: BLE001
            self._stream = None
            raise AudioDeviceError(f"cannot open the microphone at 16 kHz mono: {exc}") from exc

    def read(self, timeout: float) -> bytes | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        while True:     # drop stale audio so a reopened stream starts clean
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
