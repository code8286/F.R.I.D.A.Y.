# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Builds the voice stack from configuration and reports, in plain words, whatever is missing.

Nothing here raises for a missing library, model, key or microphone: voice degrades (and says why) instead of taking
the core down. Imports of heavy optional packages happen inside the engines, only when they are built.
"""

from __future__ import annotations

import logging
from typing import Any

from ..channels.voice import VoiceChannel
from ..core.daemon import FridayCore
from .audio_hub import AudioDeviceError, AudioHub, MicSource, import_sounddevice
from .clap import ClapConfig, ClapDetector
from .models import vosk_model_path, whisper_model_path
from .speaker import NullPlayer, SoundDevicePlayer, Speaker
from .stt import FasterWhisperTranscriber, SttUnavailable
from .tts import ElevenLabsSynth, LocalSynth, SpeechEngine, Synthesizer, TTSCache
from .vad import Endpointer, VadConfig
from .wakeword import VoskWakeEngine, WakeUnavailable, WakeWorker

log = logging.getLogger("friday.voice")


def build_voice(core: FridayCore, *, sd: Any = None) -> tuple[VoiceChannel, list[str]]:
    """Returns the channel and a list of notes (things that are off and why). `sd` is injectable for tests."""
    cfg = core.cfg
    v = cfg.voice
    notes: list[str] = []

    # ---- speaking
    engines: list[Synthesizer] = []
    if v.tts_engine == "elevenlabs":
        engines.append(
            ElevenLabsSynth(v.elevenlabs_voice_id, lambda: core.secrets.get(v.elevenlabs_secret), model_id=v.elevenlabs_model, output_format=v.elevenlabs_format)
        )
        engines.append(LocalSynth())
    elif v.tts_engine == "local":
        engines.append(LocalSynth())
    cache = TTSCache(cfg.data_dir / "cache" / "tts", v.tts_cache_max_mb * 1_000_000) if v.tts_cache else None
    engine = SpeechEngine(engines, cache, on_warning=lambda m: core.bus.publish("core.warning", {"message": m}))
    if not engines:
        notes.append("voice: speaking is off (voice.tts_engine = \"none\")")
    elif not engine.usable():
        notes.append("voice: no speech engine is usable (" + "; ".join(f"{e.name}: {e.available()}" for e in engines) + ")")
    player: Any = SoundDevicePlayer(v.output_device, sd=sd)
    why = player.available()
    if why:
        notes.append(f"voice: speaking is off ({why})")
        player = NullPlayer()
    speaker = Speaker(engine, player)

    # ---- hearing
    stt: FasterWhisperTranscriber | None = FasterWhisperTranscriber(
        whisper_model_path(cfg), language=v.stt_language, device=v.stt_device, compute_type=v.stt_compute_type
    )
    try:
        assert stt is not None
        stt.check()
    except SttUnavailable as exc:
        notes.append(f"voice: listening is off ({exc})")
        stt = None

    hub: AudioHub | None = None
    clap = ClapDetector(ClapConfig(spike_ratio=v.clap_spike_ratio, min_rms=v.clap_min_rms, max_gap_s=v.clap_max_gap_s)) if v.activation != "wake" else None
    wake: WakeWorker | None = None
    if stt is not None:
        try:
            sd_mod = sd or import_sounddevice()
        except AudioDeviceError as exc:
            notes.append(f"voice: listening is off ({exc})")
        else:
            mic = MicSource(v.input_device, sd=sd_mod)
            hub = AudioHub(
                lambda: mic,
                on_event=lambda kind, msg: core.bus.publish_threadsafe("core.warning", {"message": f"microphone {kind}: {msg}"}),
            )
        if hub is not None and v.activation in ("either", "both", "wake"):
            try:
                wake = WakeWorker(VoskWakeEngine(vosk_model_path(cfg), v.wake_phrases, v.stop_phrases), lambda e, t: None)
            except WakeUnavailable as exc:
                notes.append(f"voice: the wake phrase is off ({exc})")
        if hub is not None and wake is None and v.activation in ("wake", "both"):
            notes.append(f'voice: activation = "{v.activation}" needs the wake phrase, which is off, so the session cannot be opened by voice')

    endpointer = Endpointer(VadConfig(min_rms=v.vad_min_rms, silence_ms=v.vad_silence_ms, max_utterance_s=v.max_utterance_s))
    channel = VoiceChannel(core, v, hub=hub, speaker=speaker, stt=stt, clap=clap, endpointer=endpointer, wake=wake)
    return channel, notes
