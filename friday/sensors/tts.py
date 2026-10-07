# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Text-to-speech (Architecture §2): ElevenLabs first, a local system voice as the fallback.

* ElevenLabs is called over HTTPS with the standard library (no SDK). The API key comes from the OS keyring, never
  from config. The request goes to one fixed host, redirects are refused (so the key can never follow one elsewhere),
  and the response size is capped. THE TEXT OF EACH SPOKEN REPLY IS SENT TO ELEVENLABS; the voice channel redacts
  secrets before it gets here, and only short canned phrases (the greeting, acknowledgements) are cached on disk.
* The local voice is Windows SAPI (System.Speech via PowerShell), macOS `say`, or Linux `espeak-ng`. The text goes in
  on stdin, never on the command line, so no spoken text can become a shell argument.
* Both return PCM; playback is a separate step (player.py), so barge-in and echo gating work the same for either.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..core.errors import FridayError

log = logging.getLogger("friday.tts")

MAX_TTS_CHARS = 1500
MAX_AUDIO_BYTES = 20_000_000


class TTSError(FridayError):
    """A synthesis attempt failed (the next engine is tried)."""


class TTSAuthError(TTSError):
    """The provider rejected the key; this engine is switched off until restart so it is not hammered."""


@dataclass(frozen=True)
class Audio:
    pcm: bytes          # 16-bit signed little-endian mono
    rate: int

    @property
    def seconds(self) -> float:
        return len(self.pcm) / 2 / self.rate if self.rate else 0.0


class Synthesizer(Protocol):
    name: str

    def available(self) -> str | None: ...                 # None if usable, else a reason it is not
    def synth(self, text: str) -> Audio: ...               # blocking


# --------------------------------------------------------------------------- WAV helpers
def wav_to_audio(data: bytes) -> Audio:
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            ch, width, rate, n = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
            if width != 2:
                raise TTSError(f"unsupported audio sample width {width * 8} bit")
            if n * ch * width > MAX_AUDIO_BYTES:
                raise TTSError("audio is too long")
            raw = wf.readframes(n)
    except (wave.Error, EOFError) as exc:
        raise TTSError(f"not valid WAV audio: {exc}") from exc
    if ch > 1:      # keep the first channel
        raw = b"".join(raw[i : i + 2] for i in range(0, len(raw) - 2 * ch + 1, 2 * ch))
    return Audio(raw, rate)


def _fix_streamed_wav(data: bytes) -> bytes:
    """espeak writes a WAV to a pipe before it knows the length, so its header says 0 or 0xFFFFFFFF. Patch the sizes."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    pos = data.find(b"data", 12)
    if pos < 0:
        return data
    out = bytearray(data)
    out[4:8] = (len(data) - 8).to_bytes(4, "little")
    out[pos + 4 : pos + 8] = (len(data) - pos - 8).to_bytes(4, "little")
    return bytes(out)


def audio_to_wav(audio: Audio) -> bytes:
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(audio.rate)
        wf.writeframes(audio.pcm)
    return bio.getvalue()


# --------------------------------------------------------------------------- cache
class TTSCache:
    """On-disk WAV cache for SHORT, fixed phrases only. Replies are never cached (they can contain personal content)."""

    MAX_TEXT = 300

    def __init__(self, directory: Path, max_bytes: int = 50_000_000):
        self.dir = Path(directory)
        self.max_bytes = max_bytes

    def key(self, engine: str, voice: str, text: str) -> str:
        return hashlib.sha256(f"{engine}|{voice}|{text}".encode()).hexdigest()[:32]

    def get(self, key: str) -> Audio | None:
        path = self.dir / f"{key}.wav"
        try:
            audio = wav_to_audio(path.read_bytes())
            os.utime(path)               # least-recently-used eviction
            return audio
        except (OSError, TTSError):
            return None

    def put(self, key: str, audio: Audio) -> None:
        if not audio.pcm:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / f"{key}.wav"
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(audio_to_wav(audio))
            os.replace(tmp, path)
            self._evict()
        except OSError as exc:
            log.warning("could not write the speech cache: %s", exc)

    def _evict(self) -> None:
        files = []
        for p in self.dir.glob("*.wav"):
            try:
                st = p.stat()
                files.append((st.st_mtime, st.st_size, p))
            except OSError:
                pass
        total = sum(s for _m, s, _p in files)
        for _m, size, p in sorted(files):
            if total <= self.max_bytes:
                break
            try:
                p.unlink()
                total -= size
            except OSError:
                pass


# --------------------------------------------------------------------------- ElevenLabs
_VOICE_ID = re.compile(r"[A-Za-z0-9]{8,40}")
_FORMAT = re.compile(r"pcm_(16000|22050|24000|44100)")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:
        return None


def _default_open(req: urllib.request.Request, timeout: float) -> Any:
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    return opener.open(req, timeout=timeout)


class ElevenLabsSynth:
    name = "elevenlabs"
    HOST = "https://api.elevenlabs.io"

    def __init__(
        self,
        voice_id: str,
        key_getter: Callable[[], str | None],
        *,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "pcm_24000",
        timeout_s: float = 20.0,
        opener: Callable[[urllib.request.Request, float], Any] = _default_open,
    ):
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.timeout_s = timeout_s
        self._key = key_getter
        self._open = opener
        self.disabled_reason: str | None = None

    @property
    def rate(self) -> int:
        m = _FORMAT.fullmatch(self.output_format)
        return int(m.group(1)) if m else 24000

    def available(self) -> str | None:
        if self.disabled_reason:
            return self.disabled_reason
        if not _VOICE_ID.fullmatch(self.voice_id or ""):
            return "no valid ElevenLabs voice id is set (voice.elevenlabs_voice_id)"
        if not _FORMAT.fullmatch(self.output_format):
            return "voice.elevenlabs_format must be one of pcm_16000, pcm_22050, pcm_24000, pcm_44100"
        if not self._key():
            return "no ElevenLabs API key (run: friday set-secret elevenlabs_api_key)"
        return None

    def synth(self, text: str) -> Audio:
        why = self.available()
        if why:
            raise TTSError(why)
        text = text[:MAX_TTS_CHARS]
        key = self._key() or ""
        req = urllib.request.Request(
            f"{self.HOST}/v1/text-to-speech/{self.voice_id}?output_format={self.output_format}",
            data=json.dumps({"text": text, "model_id": self.model_id}).encode("utf-8"),
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "*/*"},
            method="POST",
        )
        try:
            resp = self._open(req, self.timeout_s)
            try:
                deadline = time.monotonic() + self.timeout_s
                chunks: list[bytes] = []
                size = 0
                while True:
                    block = resp.read(65536)
                    if not block:
                        break
                    size += len(block)
                    if size > MAX_AUDIO_BYTES:
                        raise TTSError("ElevenLabs returned too much audio")
                    chunks.append(block)
                    if time.monotonic() > deadline:
                        raise TTSError("ElevenLabs download timed out")
            finally:
                close = getattr(resp, "close", None)
                if close:
                    close()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                self.disabled_reason = (
                    f"ElevenLabs refused the request (HTTP {exc.code}): the API key is wrong, expired, out of quota or not allowed to use this voice; "
                    "fix it with `friday set-secret elevenlabs_api_key`"
                )
                raise TTSAuthError(self.disabled_reason) from exc
            raise TTSError(f"ElevenLabs returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ValueError) as exc:
            raise TTSError(f"cannot reach ElevenLabs: {getattr(exc, 'reason', exc)}") from exc
        pcm = b"".join(chunks)
        if len(pcm) < 2:
            raise TTSError("ElevenLabs returned empty audio")
        return Audio(pcm[: len(pcm) // 2 * 2], self.rate)


# --------------------------------------------------------------------------- local system voice
_PS_SCRIPT = (
    "[Console]::InputEncoding=[System.Text.Encoding]::UTF8;"
    "$t=[Console]::In.ReadToEnd();"
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.SetOutputToWaveFile($env:FRIDAY_TTS_OUT);"
    "$s.Speak($t);$s.Dispose()"
)

Runner = Callable[..., Any]


class LocalSynth:
    name = "local"

    def __init__(self, *, platform: str | None = None, runner: Runner | None = None, which: Callable[[str], str | None] = shutil.which, timeout_s: float = 30.0):
        self.platform = platform or sys.platform
        self._run = runner or subprocess.run
        self._which = which
        self.timeout_s = timeout_s

    def _program(self) -> str | None:
        if self.platform.startswith("win"):
            # the system copy by absolute path first, so a look-alike powershell.exe earlier on PATH is never run
            root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or ""
            system = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe") if root else ""
            if system and os.path.isfile(system):
                return system
            return self._which("powershell") or self._which("pwsh")
        if self.platform == "darwin":
            return self._which("say")
        return self._which("espeak-ng") or self._which("espeak")

    def available(self) -> str | None:
        if self._program():
            return None
        if self.platform.startswith("win"):
            return "PowerShell was not found, so the Windows system voice is unavailable"
        if self.platform == "darwin":
            return "the macOS `say` command was not found"
        return "no local voice found (install espeak-ng)"

    def _argv(self, program: str, out_path: str) -> tuple[list[str], dict[str, str]]:
        if self.platform.startswith("win"):
            return [program, "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT], {"FRIDAY_TTS_OUT": out_path}
        if self.platform == "darwin":
            return [program, "-o", out_path, "--file-format=WAVE", "--data-format=LEI16@22050", "-f", "-"], {}
        return [program, "--stdout", "--stdin"], {}

    def synth(self, text: str) -> Audio:
        program = self._program()
        if not program:
            raise TTSError(self.available() or "no local voice")
        text = text[:MAX_TTS_CHARS]
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("FRIDAY_SECRET_")}
        with tempfile.TemporaryDirectory(prefix="friday-tts-") as tmp:
            out = os.path.join(tmp, "out.wav")
            argv, extra = self._argv(program, out)
            env.update(extra)
            kw: dict[str, Any] = {}
            if self.platform.startswith("win") and hasattr(subprocess, "CREATE_NO_WINDOW"):
                kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            try:
                proc = self._run(argv, input=text.encode("utf-8"), capture_output=True, timeout=self.timeout_s, check=False, env=env, **kw)
            except (OSError, subprocess.SubprocessError) as exc:
                raise TTSError(f"the local voice failed to run: {exc}") from exc
            if getattr(proc, "returncode", 1) != 0:
                raise TTSError(f"the local voice exited with status {proc.returncode}")
            if self.platform.startswith("win") or self.platform == "darwin":
                try:
                    data = Path(out).read_bytes()
                except OSError as exc:
                    raise TTSError(f"the local voice produced no audio: {exc}") from exc
            else:
                data = _fix_streamed_wav(proc.stdout)
        return wav_to_audio(data)


# --------------------------------------------------------------------------- engine chain
MIN_AUDIO_S = 0.25
MIN_S_PER_CHAR = 0.025       # real speech runs at roughly 12-18 characters a second; anything much shorter was cut off


def _check_plausible(audio: Audio, text: str) -> None:
    """A truncated or near-empty stream must not count as "spoken": the approval readback depends on it having played in full."""
    need = max(MIN_AUDIO_S, min(len(text.strip()) * MIN_S_PER_CHAR, 60.0))
    if audio.seconds < need:
        raise TTSError(f"the audio is too short for the text ({audio.seconds:.2f}s for {len(text)} characters)")


class SpeechEngine:
    """Tries each synthesizer in order; caches short fixed phrases; reports why an engine was skipped (once)."""

    def __init__(self, engines: list[Synthesizer], cache: TTSCache | None = None, on_warning: Callable[[str], None] | None = None):
        self.engines = engines
        self.cache = cache
        self._on_warning = on_warning
        self._warned: set[str] = set()

    def _warn(self, msg: str) -> None:
        if msg not in self._warned:
            self._warned.add(msg)
            log.warning("%s", msg)
            if self._on_warning:
                try:
                    self._on_warning(msg)
                except Exception:  # noqa: BLE001
                    pass

    def usable(self) -> bool:
        return any(e.available() is None for e in self.engines)

    def synth(self, text: str, *, cacheable: bool = False) -> Audio:
        use_cache = bool(self.cache and cacheable and len(text) <= TTSCache.MAX_TEXT)
        for eng in self.engines:
            why = eng.available()
            if why:
                self._warn(f"{eng.name} voice skipped: {why}")
                continue
            key = self.cache.key(eng.name, getattr(eng, "voice_id", ""), text) if use_cache and self.cache else None
            if key and self.cache:
                hit = self.cache.get(key)
                if hit:
                    return hit
            try:
                audio = eng.synth(text)
                _check_plausible(audio, text)
            except TTSAuthError as exc:
                self._warn(str(exc))
                continue
            except TTSError as exc:
                self._warn(f"{eng.name} voice failed ({exc}); using the next one")
                continue
            if key and self.cache:
                self.cache.put(key, audio)
            return audio
        raise TTSError("no speech engine is available")
