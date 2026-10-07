# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""`friday audio-devices` and `friday voice-check`: see what the audio stack has and tune it, without the model or the daemon."""

from __future__ import annotations

import importlib.util
import threading
import time
from collections.abc import Callable
from typing import Any

from ..core.config import Config
from ..security.secrets import SecretStore
from .audio_hub import AudioDeviceError, AudioHub, Frame, MicSource, import_sounddevice
from .clap import ClapConfig, ClapDetector
from .models import vosk_model_path, whisper_model_path
from .speaker import SoundDevicePlayer
from .stt import FasterWhisperTranscriber, SttUnavailable
from .tts import ElevenLabsSynth, LocalSynth, SpeechEngine, Synthesizer
from .vad import Endpointer, VadConfig
from .wakeword import VoskWakeEngine, WakeUnavailable

Out = Callable[[str], None]


def audio_devices(out: Out = print, *, sd: Any = None) -> int:
    try:
        sd = sd or import_sounddevice()
    except AudioDeviceError as exc:
        out(f"error: {exc}")
        return 1
    try:
        default_in, default_out = sd.default.device[0], sd.default.device[1]
    except Exception:  # noqa: BLE001
        default_in = default_out = None
    out("Input (microphone) devices:")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] >= 1:
            out(f"  [{i}] {d['name']}{'   <- default' if i == default_in else ''}")
    out("Output (speaker) devices:")
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] >= 1:
            out(f"  [{i}] {d['name']}{'   <- default' if i == default_out else ''}")
    out("Set voice.input_device / voice.output_device in config.toml to an index or part of a name.")
    return 0


def _have(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def voice_check(cfg: Config, secrets: SecretStore, *, seconds: float = 8.0, say_text: str = "", out: Out = print) -> int:
    v = cfg.voice
    problems = 0

    def row(ok: bool, text: str) -> None:
        nonlocal problems
        out(f"  [{'ok' if ok else '!!'}] {text}")
        problems += 0 if ok else 1

    out(f"voice.enabled = {v.enabled}   activation = {v.activation}")
    out("Packages:")
    for mod, pip in (("sounddevice", "sounddevice"), ("vosk", "vosk"), ("faster_whisper", "faster-whisper"), ("numpy", "numpy")):
        row(_have(mod), f"{pip}" + ("" if _have(mod) else f"   (pip install {pip})"))
    out("Models (never downloaded by the core; `friday fetch-models all` fetches them):")
    wp, sp = vosk_model_path(cfg), whisper_model_path(cfg)
    row(wp.is_dir(), f"wake-phrase model: {wp}")
    row(sp.is_dir(), f"speech-to-text model: {sp}")
    out("Speaking:")
    engines: list[Synthesizer] = []
    el = ElevenLabsSynth(v.elevenlabs_voice_id, lambda: secrets.get(v.elevenlabs_secret), model_id=v.elevenlabs_model, output_format=v.elevenlabs_format)
    if v.tts_engine == "elevenlabs":
        why = el.available()
        row(why is None, "ElevenLabs: ready" if why is None else f"ElevenLabs: {why}")
        engines.append(el)
    local = LocalSynth()
    why = local.available()
    row(why is None, "system voice: ready" if why is None else f"system voice: {why}")
    if v.tts_engine in ("elevenlabs", "local"):
        engines.append(local)

    try:
        sd = import_sounddevice()
    except AudioDeviceError as exc:
        out(f"Audio: [!!] {exc}")
        return 1

    if say_text:
        player = SoundDevicePlayer(v.output_device, sd=sd)
        speaker_engine = SpeechEngine(engines, None, on_warning=lambda m: out(f"  [..] {m}"))
        try:
            audio = speaker_engine.synth(say_text)
            out(f"Speaking {audio.seconds:.1f}s of audio...")
            player.play(audio, threading.Event())
        except Exception as exc:  # noqa: BLE001
            out(f"  [!!] could not speak: {exc}")
            problems += 1

    if seconds <= 0:
        return 1 if problems else 0

    out(f"\nListening for {seconds:.0f}s. Clap twice, say \"{v.wake_phrases[0]}\", and speak a sentence. Levels print twice a second.")
    clap = ClapDetector(ClapConfig(spike_ratio=v.clap_spike_ratio, min_rms=v.clap_min_rms, max_gap_s=v.clap_max_gap_s))
    wake: VoskWakeEngine | None = None
    try:
        wake = VoskWakeEngine(wp, v.wake_phrases, v.stop_phrases)
    except WakeUnavailable as exc:
        out(f"  [..] wake phrase not tested: {exc}")
    stt = FasterWhisperTranscriber(sp, language=v.stt_language, device=v.stt_device, compute_type=v.stt_compute_type)
    try:
        stt.check()
    except SttUnavailable as exc:
        out(f"  [..] speech-to-text not tested: {exc}")
        stt = None  # type: ignore[assignment]
    endpointer = Endpointer(VadConfig(min_rms=v.vad_min_rms, silence_ms=v.vad_silence_ms, max_utterance_s=v.max_utterance_s))

    state = {"peak": 0.0, "last": 0.0}
    utterances: list[Any] = []
    lock = threading.Lock()

    def consume(f: Frame) -> None:
        with lock:
            state["peak"] = max(state["peak"], f.level)
        if clap.feed(f.level, f.t):
            out("  >> double clap detected")
        if wake is not None:
            for ev in wake.feed(f.pcm):
                out(f"  >> heard: {ev}")
        u = endpointer.feed(f)
        if u is not None:
            utterances.append(u)

    mic = MicSource(v.input_device, sd=sd)
    hub = AudioHub(lambda: mic, on_event=lambda k, m: out(f"  [..] microphone {k}: {m}"))
    hub.subscribe("check", consume)
    hub.start()
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(0.5)
            with lock:
                peak, state["peak"] = state["peak"], 0.0
            bar = "#" * min(40, int(peak * 160))
            out(f"  level {peak:0.3f} {bar}   noise floor {clap.noise_floor:0.4f}   clap threshold {clap.threshold:0.3f}")
            while utterances:
                u = utterances.pop(0)
                if stt is None:
                    out(f"  >> captured {len(u.pcm) / 32000:.1f}s of speech (no speech model to transcribe it)")
                else:
                    t0 = time.monotonic()
                    text = stt.transcribe(u.pcm)
                    out(f"  >> you said: {text!r}   ({time.monotonic() - t0:.1f}s to transcribe)")
    except KeyboardInterrupt:
        pass
    finally:
        hub.stop()
    if hub.last_error:
        out(f"  [!!] microphone: {hub.last_error}")
        problems += 1
    elif hub.frames == 0:
        out("  [!!] no audio arrived from the microphone")
        problems += 1
    return 1 if problems else 0
