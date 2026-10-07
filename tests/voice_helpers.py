# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Fakes for the audio stack, so tranche 3 is tested without a microphone, speakers, Vosk, Whisper or a network."""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Callable
from typing import Any

from friday.channels.voice import VoiceChannel
from friday.core.config import VoiceConfig
from friday.core.daemon import FridayCore
from friday.sensors.audio_hub import FRAME_BYTES, FRAME_S, Frame, rms_level
from friday.sensors.clap import ClapDetector
from friday.sensors.speaker import Speaker
from friday.sensors.tts import Audio, SpeechEngine, TTSError
from friday.sensors.vad import Endpointer, Utterance


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


def tone(level: float, frames: int = 1) -> bytes:
    """`frames` 20 ms frames of a square wave whose RMS is `level` (0..1)."""
    amp = int(level * 32767)
    one = (amp.to_bytes(2, "little", signed=True) + (-amp).to_bytes(2, "little", signed=True)) * (FRAME_BYTES // 4)
    return one * frames


def make_frame(level: float, t: float) -> Frame:
    pcm = tone(level)
    return Frame(pcm, t, rms_level(pcm))


class FakeSource:
    """An AudioSource fed from a script of chunks: bytes, None (timeout) or an Exception to raise."""

    def __init__(self, script: list[Any], fail_open: int = 0):
        self.script = list(script)
        self.fail_open = fail_open
        self.opened = 0
        self.closed = 0

    def open(self) -> None:
        self.opened += 1
        if self.fail_open > 0:
            self.fail_open -= 1
            raise OSError("device busy")

    def read(self, timeout: float) -> bytes | None:
        if not self.script:
            threading.Event().wait(min(timeout, 0.01))
            return None
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed += 1


class FakeHub:
    def __init__(self) -> None:
        self.subs: dict[str, Callable[[Frame], None]] = {}
        self.started = False

    def subscribe(self, name: str, fn: Callable[[Frame], None]) -> None:
        self.subs[name] = fn

    def unsubscribe(self, name: str) -> None:
        self.subs.pop(name, None)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


class FakeSynth:
    name = "fake"

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.fail = False

    def available(self) -> str | None:
        return None

    def synth(self, text: str) -> Audio:
        if self.fail:
            raise TTSError("boom")
        self.texts.append(text)
        n = int(max(0.4, len(text) * 0.03) * 16000)          # long enough to count as fully spoken
        return Audio(b"\x01\x00" * n, 16000)


class FakePlayer:
    """Records what was played. `block` makes playback wait (until released or interrupted), like a long sentence."""

    def __init__(self) -> None:
        self.played: list[Audio] = []
        self.block: threading.Event | None = None
        self.started = threading.Event()

    def available(self) -> str | None:
        return None

    def play(self, audio: Audio, stop: threading.Event) -> bool:
        self.started.set()
        gate = self.block
        if gate is not None:
            while not gate.is_set():
                if stop.is_set():
                    return False
                gate.wait(0.005)
        if stop.is_set():
            return False
        self.played.append(audio)
        return True


class FakeStt:
    def __init__(self) -> None:
        self.texts: queue.Queue[str] = queue.Queue()
        self.calls = 0

    def say(self, text: str) -> None:
        self.texts.put(text)

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        self.calls += 1
        try:
            return self.texts.get_nowait()
        except queue.Empty:
            return ""


class VoiceRig:
    def __init__(self, core: FridayCore, channel: VoiceChannel, synth: FakeSynth, player: FakePlayer, stt: FakeStt, clock: FakeClock, hub: FakeHub):
        self.core, self.channel, self.synth, self.player, self.stt, self.clock, self.hub = core, channel, synth, player, stt, clock, hub

    @property
    def spoken(self) -> list[str]:
        return list(self.synth.texts)

    async def activate(self, sources: tuple[str, ...] = ("clap",)) -> None:
        self.channel._on_activate(sources)
        await self.settle()

    async def hear(self, text: str) -> None:
        """Deliver one utterance (already past the recorder) whose transcript is `text`."""
        self.stt.say(text)
        self.channel._enqueue_utterance(Utterance(b"\x00\x00" * 8000, 0.0, 0.5, "silence"))
        await self.settle()

    async def settle(self, rounds: int = 40) -> None:
        for _ in range(rounds):
            await asyncio.sleep(0.005)

    async def until(self, cond: Callable[[], bool], timeout: float = 3.0) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while not cond():
            if loop.time() > end:
                raise AssertionError("condition not reached in time")
            await asyncio.sleep(0.005)


async def make_voice(core: FridayCore, **cfg_overrides: Any) -> VoiceRig:
    cfg = VoiceConfig(enabled=True, **cfg_overrides)
    clock = FakeClock()
    synth, player, stt, hub = FakeSynth(), FakePlayer(), FakeStt(), FakeHub()
    speaker = Speaker(SpeechEngine([synth]), player, clock=clock)
    channel = VoiceChannel(
        core, cfg, hub=hub, speaker=speaker, stt=stt, clap=ClapDetector(), endpointer=Endpointer(), wake=None, clock=clock,  # type: ignore[arg-type]
    )
    channel.idle_poll_s = 0.01
    await channel.start()
    return VoiceRig(core, channel, synth, player, stt, clock, hub)


__all__ = ["FRAME_S", "FakeClock", "FakeHub", "FakePlayer", "FakeSource", "FakeStt", "FakeSynth", "VoiceRig", "make_frame", "make_voice", "tone"]
