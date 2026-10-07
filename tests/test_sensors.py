# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Tranche 3 building blocks: hub, clap, VAD, wake, fusion, STT, TTS, player, speech text, models."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace

from friday.core.config import Config
from friday.security.card import build_readback, render_readback
from friday.security.policy import Decision
from friday.security.tiers import RiskTier
from friday.sensors import models as mdl
from friday.sensors.activation import ActivationFusion
from friday.sensors.audio_hub import FRAME_BYTES, FRAME_S, AudioDeviceError, AudioHub, Frame, MicSource, pick_input_device, rms_level
from friday.sensors.clap import ClapConfig, ClapDetector
from friday.sensors.speaker import SoundDevicePlayer, Speaker
from friday.sensors.speech_text import is_negative, meaningful, speakable, strip_unspeakable
from friday.sensors.stt import FasterWhisperTranscriber, SttUnavailable
from friday.sensors.tts import (
    Audio,
    ElevenLabsSynth,
    LocalSynth,
    SpeechEngine,
    TTSAuthError,
    TTSCache,
    TTSError,
    audio_to_wav,
    wav_to_audio,
)
from friday.sensors.vad import Endpointer, VadConfig
from friday.sensors.wakeword import STOP, WAKE, VoskWakeEngine, WakeUnavailable, WakeWorker, match_phrase
from tests.helpers import AsyncTempDirCase, TempDirCase
from tests.voice_helpers import FakePlayer, FakeSource, FakeSynth, make_frame, tone

HAVE_NUMPY = importlib.util.find_spec("numpy") is not None


# --------------------------------------------------------------------------- audio hub
class HubTests(unittest.TestCase):
    def test_rms_level(self):
        self.assertEqual(rms_level(b""), 0.0)
        self.assertEqual(rms_level(b"\x00\x00" * 100), 0.0)
        self.assertAlmostEqual(rms_level(tone(0.5)), 0.5, places=2)

    def collect(self, hub, seconds=0.6):
        frames: list[Frame] = []
        hub.subscribe("t", frames.append)
        hub.start()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            time.sleep(0.01)
        hub.stop()
        return frames

    def test_chunks_are_reframed_to_20ms_with_sample_counter_time(self):
        odd = tone(0.1, 3)                      # three frames' worth, delivered in awkward pieces
        script = [odd[:100], odd[100:1000], odd[1000:]]
        hub = AudioHub(lambda: FakeSource(script), stall_s=60)
        frames = self.collect(hub, 0.3)
        self.assertEqual(len(frames), 3)
        self.assertTrue(all(len(f.pcm) == FRAME_BYTES for f in frames))
        self.assertAlmostEqual(frames[1].t - frames[0].t, FRAME_S, places=6)
        self.assertAlmostEqual(frames[0].level, 0.1, places=2)

    def test_open_failure_is_retried_and_reported_once(self):
        events: list[tuple[str, str]] = []
        src = FakeSource([tone(0.1, 2)], fail_open=3)
        hub = AudioHub(lambda: src, on_event=lambda k, m: events.append((k, m)), retry_s=0.02, stall_s=60)
        frames = self.collect(hub, 0.6)
        self.assertEqual(len(frames), 2)
        kinds = [k for k, _ in events]
        self.assertEqual(kinds.count("error"), 1)         # three identical failures, one report
        self.assertEqual(kinds[-1], "recovered")
        self.assertIn("device busy", events[0][1])

    def test_stream_error_and_stall_trigger_a_reopen(self):
        src = FakeSource([tone(0.1, 1), OSError("unplugged")])
        opened: list[FakeSource] = []

        def factory():
            opened.append(src)
            return src

        hub = AudioHub(factory, retry_s=0.02, stall_s=0.05)
        self.collect(hub, 0.5)
        self.assertGreaterEqual(src.opened, 2)            # reopened after the error, and again after the stall
        self.assertGreaterEqual(src.closed, 2)

    def test_a_broken_consumer_does_not_stop_the_others(self):
        hub = AudioHub(lambda: FakeSource([tone(0.1, 4)]), stall_s=60)
        seen: list[Frame] = []

        def bad(f):
            raise RuntimeError("detector bug")

        hub.subscribe("bad", bad)
        hub.subscribe("good", seen.append)
        hub.start()
        time.sleep(0.3)
        hub.stop()
        self.assertEqual(len(seen), 4)

    def test_stop_is_prompt_and_idempotent(self):
        hub = AudioHub(lambda: FakeSource([]), stall_s=60)
        hub.start()
        t0 = time.monotonic()
        hub.stop()
        hub.stop()
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual(hub.state, "stopped")


class FakeSd:
    """Just enough of sounddevice for device selection and the player."""

    def __init__(self, devices, default=(0, 1), levels=None):
        self._devices = devices
        self.default = SimpleNamespace(device=default)
        self.levels = levels or {}
        self.streams: list = []

    def query_devices(self, idx=None):
        if idx is None:
            return self._devices
        if not 0 <= idx < len(self._devices):
            raise ValueError("no such device")
        return self._devices[idx]

    def RawInputStream(self, **kw):   # noqa: N802
        dev = kw.get("device")
        level = self.levels.get(dev if dev is not None else self.default.device[0], 0.0)
        if level is None:
            raise OSError("cannot open")

        class S:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def read(s, n):
                return tone(level), False

        return S()

    def RawOutputStream(self, **kw):   # noqa: N802
        outer = self

        class Out:
            def __init__(s):
                s.written = b""
                s.aborted = False
                s.stopped = False
                outer.streams.append(s)

            def start(s):
                pass

            def write(s, b):
                s.written += b

            def abort(s):
                s.aborted = True

            def stop(s):
                s.stopped = True

            def close(s):
                pass

        return Out()


class DeviceTests(unittest.TestCase):
    DEVS = [
        {"name": "Built-in Mic", "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2},
        {"name": "USB Headset", "max_input_channels": 1, "max_output_channels": 2},
    ]

    def test_configured_device_by_index_and_name(self):
        sd = FakeSd(self.DEVS)
        self.assertEqual(pick_input_device(sd, "2"), 2)
        self.assertEqual(pick_input_device(sd, "usb"), 2)
        with self.assertRaises(AudioDeviceError):
            pick_input_device(sd, "nonexistent")
        with self.assertRaises(ValueError):
            pick_input_device(sd, "9")

    def test_default_used_when_it_has_signal(self):
        sd = FakeSd(self.DEVS, default=(0, 1), levels={0: 0.05, 2: 0.3})
        self.assertEqual(pick_input_device(sd, ""), 0)

    def test_silent_default_falls_back_to_loudest_input(self):
        sd = FakeSd(self.DEVS, default=(0, 1), levels={0: 0.0, 2: 0.2})
        self.assertEqual(pick_input_device(sd, ""), 2)

    def test_loopback_inputs_are_never_chosen_as_a_microphone(self):
        devs = [*self.DEVS, {"name": "Stereo Mix (Realtek)", "max_input_channels": 2, "max_output_channels": 0}]
        sd = FakeSd(devs, default=(0, 1), levels={0: 0.0, 2: 0.0, 3: 0.5})     # the mix is the "loudest" (it hears FRIDAY itself)
        self.assertEqual(pick_input_device(sd, ""), 0)

    def test_all_silent_keeps_the_default(self):
        sd = FakeSd(self.DEVS, default=(0, 1), levels={0: 0.0, 2: 0.0})
        self.assertEqual(pick_input_device(sd, ""), 0)

    def test_mic_source_open_read_close(self):
        class Stream:
            def __init__(s, **kw):
                s.cb = kw["callback"]
                s.kw = kw
                s.started = s.stopped = s.closed = False

            def start(s):
                s.started = True

            def stop(s):
                s.stopped = True

            def close(s):
                s.closed = True

        made: list[Stream] = []

        class Sd(FakeSd):
            def RawInputStream(self, **kw):   # noqa: N802
                if "callback" not in kw:
                    return super().RawInputStream(**kw)
                made.append(Stream(**kw))
                return made[-1]

        sd = Sd(self.DEVS, levels={0: 0.1})
        mic = MicSource("", sd=sd)
        mic.open()
        st = made[0]
        self.assertEqual((st.kw["samplerate"], st.kw["channels"], st.kw["dtype"]), (16000, 1, "int16"))
        st.cb(b"\x01\x00" * 320, 320, None, None)
        self.assertEqual(mic.read(0.1), b"\x01\x00" * 320)
        self.assertIsNone(mic.read(0.01))
        for _ in range(MicSource.MAX_QUEUED_CHUNKS + 20):    # a stalled consumer must not grow the queue forever
            st.cb(b"\x00\x00" * 320, 320, None, None)
        self.assertGreater(mic.dropped, 0)
        mic.close()
        self.assertTrue(st.stopped and st.closed)
        self.assertIsNone(mic.read(0.01))


# --------------------------------------------------------------------------- clap detector
def run_clap(levels, cfg=None):
    d = ClapDetector(cfg)
    t, hits = 0.0, []
    for lvl in levels:
        if d.feed(lvl, t):
            hits.append(round(t, 3))
        t += FRAME_S
    return hits, d


QUIET = [0.001] * 100          # 2 s of room tone (also clears the 1 s warm-up)
CLAP = [0.2, 0.05]             # a loud frame, then the tail
GAP = lambda n: [0.001] * n    # noqa: E731


class ClapTests(unittest.TestCase):
    def test_double_clap_is_detected(self):
        hits, _ = run_clap(QUIET + CLAP + GAP(8) + CLAP + GAP(20))
        self.assertEqual(len(hits), 1)

    def test_single_clap_and_slow_pairs_are_not(self):
        self.assertEqual(run_clap(QUIET + CLAP + GAP(30))[0], [])
        self.assertEqual(run_clap(QUIET + CLAP + GAP(40) + CLAP + GAP(20))[0], [])      # 0.8 s apart

    def test_a_long_loud_sound_is_not_a_clap(self):
        # Two 300 ms bursts 150 ms apart look like a double spike to a plain threshold; speech does exactly this.
        self.assertEqual(run_clap(QUIET + [0.1] * 15 + GAP(7) + [0.1] * 15 + GAP(20))[0], [])
        self.assertEqual(run_clap(QUIET + [0.2] * 30 + GAP(30))[0], [])

    def test_warmup_ignores_startup_noise(self):
        self.assertEqual(run_clap(CLAP + GAP(5) + CLAP + GAP(20))[0], [])

    def test_cooldown_and_second_pair(self):
        hits, _ = run_clap(QUIET + CLAP + GAP(8) + CLAP + GAP(5) + CLAP + GAP(8) + CLAP + GAP(30))
        self.assertEqual(len(hits), 1)       # the second pair began inside the 0.45 s cooldown
        hits, _ = run_clap(QUIET + CLAP + GAP(8) + CLAP + GAP(40) + CLAP + GAP(8) + CLAP + GAP(30))
        self.assertEqual(len(hits), 2)       # a second pair a second later counts

    def test_can_fire_repeatedly(self):
        """The old script ran its welcome once per process; the detector itself has no such limit."""
        seq = QUIET + (CLAP + GAP(8) + CLAP + GAP(60)) * 3
        self.assertEqual(len(run_clap(seq)[0]), 3)

    def test_threshold_never_below_min_rms(self):
        _, d = run_clap([0.0] * 200)
        self.assertGreaterEqual(d.threshold, ClapConfig().min_rms)
        self.assertEqual(run_clap(QUIET + [0.008, 0.001] + GAP(8) + [0.008, 0.001] + GAP(20))[0], [])

    def test_floor_follows_sustained_noise_up(self):
        _, d = run_clap([0.003] * 5000)       # 100 s of steady hum, below the clap threshold
        self.assertGreater(d.noise_floor, 0.002)


# --------------------------------------------------------------------------- VAD
def run_vad(levels, cfg=None):
    e = Endpointer(cfg)
    out, t = [], 0.0
    for lvl in levels:
        pcm = b"\x00\x00" * 320
        u = e.feed(Frame(pcm, t, lvl))
        if u:
            out.append(u)
        t += FRAME_S
    return out


class VadTests(unittest.TestCase):
    def test_one_utterance_with_preroll_and_silence_end(self):
        [u] = run_vad([0.001] * 50 + [0.05] * 30 + [0.001] * 50)
        self.assertEqual(u.reason, "silence")
        self.assertAlmostEqual(u.start_t, 50 * FRAME_S - 0.3 + 0.0, delta=0.05)    # 300 ms of pre-roll
        self.assertGreaterEqual(len(u.pcm) // FRAME_BYTES, 30 + 15)

    def test_short_bursts_are_discarded(self):
        self.assertEqual(run_vad([0.001] * 50 + [0.05] * 4 + [0.001] * 60), [])      # 80 ms: a click, not speech

    def test_pause_inside_speech_does_not_split_it(self):
        us = run_vad([0.001] * 50 + [0.05] * 20 + [0.001] * 15 + [0.05] * 20 + [0.001] * 50)     # 300 ms pause < 700 ms
        self.assertEqual(len(us), 1)

    def test_two_utterances(self):
        self.assertEqual(len(run_vad(([0.001] * 50 + [0.05] * 25 + [0.001] * 50) * 2)), 2)

    def test_max_length_cuts_a_never_ending_utterance(self):
        us = run_vad([0.001] * 50 + [0.05] * 1000, VadConfig(max_utterance_s=3.0))
        self.assertTrue(us and us[0].reason == "max")
        self.assertLessEqual(len(us[0].pcm) / FRAME_BYTES * FRAME_S, 3.2)

    def test_reset_drops_a_partial_utterance(self):
        e = Endpointer()
        for i in range(60):
            e.feed(Frame(b"\x00\x00" * 320, i * FRAME_S, 0.05))
        self.assertTrue(e.in_speech)
        e.reset()
        self.assertFalse(e.in_speech)

    def test_quiet_room_noise_does_not_start_speech(self):
        self.assertEqual(run_vad([0.004] * 500), [])


# --------------------------------------------------------------------------- wake phrase
class FakeKaldi:
    """Stands in for vosk: a scripted recogniser. `script` maps call number -> (is_final, text)."""

    def __init__(self, script):
        self.script = script
        self.calls = 0
        self.resets = 0
        self.grammar = None
        self.last = ""

    def AcceptWaveform(self, data):   # noqa: N802
        self.calls += 1
        final, self.last = self.script.get(self.calls, (False, ""))
        return final

    def Result(self):   # noqa: N802
        return json.dumps({"text": self.last})

    def PartialResult(self):   # noqa: N802
        return json.dumps({"partial": self.last})

    def Reset(self):   # noqa: N802
        self.resets += 1


def fake_vosk(script):
    rec = FakeKaldi(script)

    def Recognizer(model, rate, grammar):   # noqa: N802
        rec.grammar = json.loads(grammar)
        assert rate == 16000
        return rec

    return SimpleNamespace(SetLogLevel=lambda n: None, Model=lambda p: object(), KaldiRecognizer=Recognizer), rec


class WakeTests(TempDirCase):
    def test_match_phrase(self):
        self.assertEqual(match_phrase("hey friday wake up please", ["friday wake up"]), "friday wake up")
        self.assertIsNone(match_phrase("friday wake", ["friday wake up"]))
        self.assertIsNone(match_phrase("fridays wake up", ["friday wake up"]))
        self.assertEqual(match_phrase("STOP!", ["stop"]), "stop")

    def engine(self, script):
        vosk, rec = fake_vosk(script)
        return VoskWakeEngine(self.tmp, ["friday wake up"], ["stop", "friday stop"], vosk=vosk), rec

    def test_grammar_is_restricted_to_the_phrases(self):
        _, rec = self.engine({})
        self.assertEqual(rec.grammar, ["friday wake up", "stop", "friday stop", "[unk]"])

    def test_partial_and_final_results_fire_once(self):
        eng, rec = self.engine({1: (False, "friday wake up"), 2: (True, "friday wake up"), 3: (False, "stop")})
        chunk = b"\x00\x00" * 1600
        self.assertEqual(eng.feed(chunk), [WAKE])
        self.assertEqual(rec.resets, 1)
        self.assertEqual(eng.feed(chunk), [WAKE])
        self.assertEqual(eng.feed(chunk), [STOP])

    def test_small_frames_are_batched_to_100ms(self):
        eng, rec = self.engine({1: (False, "friday wake up")})
        frame = b"\x00\x00" * 320
        for _ in range(4):
            self.assertEqual(eng.feed(frame), [])
        self.assertEqual(rec.calls, 0)
        self.assertEqual(eng.feed(frame), [WAKE])        # fifth frame: 100 ms

    def test_unrelated_speech_is_ignored(self):
        eng, _ = self.engine({1: (True, "what time is it"), 2: (False, "[unk]")})
        self.assertEqual(eng.feed(b"\x00\x00" * 1600), [])
        self.assertEqual(eng.feed(b"\x00\x00" * 1600), [])

    def test_missing_model_and_library_are_clean_errors(self):
        with self.assertRaises(WakeUnavailable) as cm:
            VoskWakeEngine(self.tmp / "nope", ["friday wake up"], [], vosk=fake_vosk({})[0])
        self.assertIn("fetch-models", str(cm.exception))
        with self.assertRaises(WakeUnavailable):
            VoskWakeEngine(self.tmp, [], [], vosk=fake_vosk({})[0])

    def test_worker_delivers_events_drops_when_behind_and_survives_a_dead_engine(self):
        got: list[tuple[str, float]] = []
        done = threading.Event()

        class Eng:
            def feed(self, pcm):
                return [WAKE] if pcm == b"w" else []

        w = WakeWorker(Eng(), lambda e, t: (got.append((e, t)), done.set()))
        w.start()
        w.offer(Frame(b"w", 1.5, 0.0))
        self.assertTrue(done.wait(2))
        w.stop()
        self.assertEqual(got, [(WAKE, 1.5)])

        class Dead:
            def feed(self, pcm):
                raise RuntimeError("model crashed")

        w = WakeWorker(Dead(), lambda e, t: None)
        w.start()
        w.offer(Frame(b"x", 0, 0))
        for _ in range(100):
            if w.failed:
                break
            time.sleep(0.01)
        self.assertIn("model crashed", w.failed or "")
        w.offer(Frame(b"x", 0, 0))      # ignored, no exception
        w.stop()

        slow = threading.Event()

        class Slow:
            def feed(self, pcm):
                slow.wait(1)
                return []

        w = WakeWorker(Slow(), lambda e, t: None, maxsize=2)
        w.start()
        for _ in range(20):
            w.offer(Frame(b"x", 0, 0))
        self.assertGreater(w.dropped, 0)
        slow.set()
        w.stop()


# --------------------------------------------------------------------------- activation fusion
class FusionTests(unittest.TestCase):
    def make(self, mode, **kw):
        fired: list[tuple[str, ...]] = []
        t = [100.0]
        f = ActivationFusion(mode, fired.append, clock=lambda: t[0], **kw)
        return f, fired, t

    def test_either_fires_on_each_and_debounces(self):
        f, fired, t = self.make("either", debounce_s=3.0)
        self.assertTrue(f.trigger("clap"))
        self.assertFalse(f.trigger("wake"))            # the same moment, heard twice
        t[0] += 3.5
        self.assertTrue(f.trigger("wake"))
        self.assertEqual(fired, [("clap",), ("wake",)])

    def test_single_source_modes(self):
        f, fired, _ = self.make("clap")
        self.assertFalse(f.trigger("wake"))
        self.assertTrue(f.trigger("clap"))
        f, fired, _ = self.make("wake")
        self.assertFalse(f.trigger("clap"))
        self.assertTrue(f.trigger("wake"))

    def test_both_needs_both_within_the_window(self):
        f, fired, t = self.make("both", both_window_s=4.0, debounce_s=0.0)
        self.assertFalse(f.trigger("clap"))
        t[0] += 2
        self.assertTrue(f.trigger("wake"))
        self.assertEqual(fired, [("clap", "wake")])
        self.assertFalse(f.trigger("clap"))
        t[0] += 10                                       # too late for the pair
        self.assertFalse(f.trigger("wake"))

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            ActivationFusion("sometimes", lambda s: None)


# --------------------------------------------------------------------------- speech text
class SpeechTextTests(unittest.TestCase):
    def test_speakable_strips_code_links_markdown(self):
        t = speakable("Here you go:\n```py\nprint(1)\n```\nSee **https://example.com/x?y=1** and `task_add`.\n- one\n- two")
        self.assertNotIn("print", t)
        self.assertNotIn("http", t)
        self.assertNotIn("*", t)
        self.assertIn("a link", t)
        self.assertIn("code omitted", t)
        self.assertNotIn("\n", t)

    def test_long_text_is_cut_at_a_sentence_and_points_to_the_screen(self):
        text = "First sentence here. " * 60
        t = speakable(text, max_chars=100)
        self.assertLessEqual(len(t), 140)
        self.assertTrue(t.endswith("The rest is on screen."))
        self.assertIn("First sentence here.", t)

    def test_control_and_bidi_characters_are_dropped(self):
        self.assertEqual(strip_unspeakable("a\u202eb\u200bc\x07d\n e"), "abcd e")

    def test_negatives_and_filler(self):
        for s in ("no", "No, cancel that", "don't do it", "stop"):
            self.assertTrue(is_negative(s), s)
        for s in ("yes", "yes please", "go ahead"):
            self.assertFalse(is_negative(s), s)
        self.assertFalse(meaningful(""))
        self.assertFalse(meaningful("..."))
        self.assertFalse(meaningful("um"))
        self.assertFalse(meaningful("you"))
        self.assertFalse(meaningful("thank you"))                 # a classic Whisper hallucination on silence
        self.assertFalse(meaningful("Thank you for watching."))
        self.assertTrue(meaningful("what's on my list"))


# --------------------------------------------------------------------------- stt
@unittest.skipUnless(HAVE_NUMPY, "numpy is not installed")
class SttTests(TempDirCase):
    def test_transcribes_with_the_expected_model_arguments(self):
        seen = {}

        class Model:
            def __init__(self, path, **kw):
                seen["load"] = (path, kw)

            def transcribe(self, audio, **kw):
                seen["audio"] = audio
                seen["kw"] = kw
                segs = [
                    SimpleNamespace(text=" what time is it ", no_speech_prob=0.01, avg_logprob=-0.2),
                    SimpleNamespace(text=" Thank you. ", no_speech_prob=0.9, avg_logprob=-2.0),     # a hallucination on silence
                ]
                return iter(segs), None

        stt = FasterWhisperTranscriber(self.tmp, model_factory=Model, initial_prompt="FRIDAY")
        self.assertEqual(stt.transcribe(tone(0.1, 20)), "what time is it")
        self.assertEqual(seen["load"][0], str(self.tmp))
        self.assertTrue(seen["load"][1]["local_files_only"])             # the running core never downloads
        self.assertEqual(seen["audio"].dtype.name, "float32")
        self.assertLessEqual(float(abs(seen["audio"]).max()), 1.0)
        self.assertEqual(seen["kw"]["language"], "en")
        self.assertFalse(seen["kw"]["condition_on_previous_text"])

    def test_device_auto_falls_back_to_the_cpu_when_the_gpu_stack_is_broken(self):
        tries = []

        class Model:
            def __init__(self, path, **kw):
                tries.append(kw["device"])
                if kw["device"] != "cpu":
                    raise RuntimeError("cuDNN not found")

            def transcribe(self, audio, **kw):
                return iter([SimpleNamespace(text="hello", no_speech_prob=0.0, avg_logprob=-0.1)]), None

        self.assertEqual(FasterWhisperTranscriber(self.tmp, model_factory=Model, device="auto").transcribe(tone(0.1, 20)), "hello")
        self.assertEqual(tries, ["auto", "cpu"])
        tries.clear()
        with self.assertRaises(SttUnavailable):
            FasterWhisperTranscriber(self.tmp, model_factory=Model, device="cuda").transcribe(tone(0.1, 20))
        self.assertEqual(tries, ["cuda"])                                  # an explicit choice is respected

    def test_very_short_audio_is_empty_and_model_loads_once(self):
        loads = []

        class Model:
            def __init__(self, *a, **k):
                loads.append(1)

            def transcribe(self, audio, **kw):
                return iter([SimpleNamespace(text="hi", no_speech_prob=0, avg_logprob=0)]), None

        stt = FasterWhisperTranscriber(self.tmp, model_factory=Model)
        self.assertEqual(stt.transcribe(b"\x00\x00" * 100), "")
        stt.transcribe(tone(0.1, 10))
        stt.transcribe(tone(0.1, 10))
        self.assertEqual(len(loads), 1)

    def test_missing_model_folder_is_a_clean_error(self):
        stt = FasterWhisperTranscriber(self.tmp / "none", model_factory=lambda *a, **k: None)
        with self.assertRaises(SttUnavailable) as cm:
            stt.check()
        self.assertIn("fetch-models", str(cm.exception))

    def test_load_failure_is_wrapped(self):
        def bad(*a, **k):
            raise RuntimeError("corrupt model.bin")

        with self.assertRaises(SttUnavailable):
            FasterWhisperTranscriber(self.tmp, model_factory=bad).transcribe(tone(0.1, 10)) if HAVE_NUMPY else None


# --------------------------------------------------------------------------- tts
class FakeResp:
    def __init__(self, data: bytes):
        self.bio = io.BytesIO(data)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False

    def read(self, n=-1):
        return self.bio.read(n)

    def close(self):
        self.closed = True


class ElevenLabsTests(unittest.TestCase):
    def make(self, opener, key="xi-test-key-123456", voice="VoiceId12345", **kw):
        return ElevenLabsSynth(voice, lambda: key, opener=opener, **kw)

    def test_request_shape_and_pcm_result(self):
        seen = {}

        def opener(req, timeout):
            seen["url"], seen["headers"], seen["body"], seen["timeout"], seen["method"] = req.full_url, dict(req.header_items()), json.loads(req.data), timeout, req.method
            return FakeResp(b"\x01\x00" * 2400)

        a = self.make(opener).synth("Hello there")
        self.assertEqual(a.rate, 24000)
        self.assertEqual(len(a.pcm), 4800)
        self.assertEqual(seen["url"], "https://api.elevenlabs.io/v1/text-to-speech/VoiceId12345?output_format=pcm_24000")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["body"], {"text": "Hello there", "model_id": "eleven_multilingual_v2"})
        self.assertEqual(seen["headers"]["Xi-api-key"], "xi-test-key-123456")

    def test_voice_id_cannot_inject_into_the_url(self):
        for bad in ("../../admin", "abc/def", "voice id", "", "x" * 80):
            self.assertIsNotNone(self.make(lambda r, t: FakeResp(b"\x00\x00"), voice=bad).available(), bad)
        self.assertIsNotNone(self.make(lambda r, t: None, output_format="mp3_44100_128").available())

    def test_no_key_is_not_available(self):
        self.assertIn("API key", self.make(lambda r, t: None, key="").available())

    def test_auth_failure_switches_the_engine_off(self):
        calls = []

        def opener(req, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        e = self.make(opener)
        with self.assertRaises(TTSAuthError):
            e.synth("hi")
        self.assertIn("refused", e.available() or "")
        with self.assertRaises(TTSError):
            e.synth("hi again")
        self.assertEqual(len(calls), 1)                  # not hammered

    def test_server_and_network_errors_are_ordinary_failures(self):
        def boom(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)

        with self.assertRaises(TTSError):
            self.make(boom).synth("hi")
        self.assertIsNone(self.make(boom).available())    # transient: stays enabled

        def down(req, timeout):
            raise urllib.error.URLError("no route")

        with self.assertRaises(TTSError):
            self.make(down).synth("hi")

    def test_redirects_are_never_followed(self):
        from friday.sensors.tts import _NoRedirect

        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example/"))

    def test_empty_and_oversized_responses_are_rejected(self):
        with self.assertRaises(TTSError):
            self.make(lambda r, t: FakeResp(b"")).synth("x")
        import friday.sensors.tts as tts

        old = tts.MAX_AUDIO_BYTES
        tts.MAX_AUDIO_BYTES = 1000
        try:
            with self.assertRaises(TTSError):
                self.make(lambda r, t: FakeResp(b"\x00" * 200000)).synth("x")
        finally:
            tts.MAX_AUDIO_BYTES = old

    def test_the_response_is_closed(self):
        resp = FakeResp(b"\x00\x00" * 10)
        self.make(lambda r, t: resp).synth("x")
        self.assertTrue(resp.closed)


class LocalSynthTests(unittest.TestCase):
    def wav(self, rate=22050, channels=1, n=500):
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(b"\x02\x00" * channels * n)
        return bio.getvalue()

    def runner(self, record, wav_bytes, platform):
        def run(argv, **kw):
            record.update(argv=argv, kw=kw)
            if platform.startswith("win") or platform == "darwin":
                Path(kw["env"].get("FRIDAY_TTS_OUT") or argv[argv.index("-o") + 1]).write_bytes(wav_bytes)
                return SimpleNamespace(returncode=0, stdout=b"")
            return SimpleNamespace(returncode=0, stdout=wav_bytes)

        return run

    def test_each_platform_passes_text_on_stdin_never_in_argv(self):
        text = "Hello; rm -rf / && $(evil) \"quoted\" -- --help"
        for platform, prog in (("win32", "powershell"), ("darwin", "say"), ("linux", "espeak-ng")):
            rec: dict = {}
            s = LocalSynth(platform=platform, runner=self.runner(rec, self.wav(), platform), which=lambda n, p=prog: f"/bin/{n}" if n == p else None)
            a = s.synth(text)
            self.assertEqual(a.rate, 22050)
            self.assertEqual(rec["kw"]["input"], text.encode())
            self.assertNotIn(text, " ".join(rec["argv"]), platform)
            self.assertIsInstance(rec["argv"], list)                     # argv, no shell string
            self.assertNotIn("shell", rec["kw"])

    def test_windows_output_path_goes_through_the_environment(self):
        rec: dict = {}
        LocalSynth(platform="win32", runner=self.runner(rec, self.wav(), "win32"), which=lambda n: "powershell").synth("hi")
        self.assertIn("FRIDAY_TTS_OUT", rec["kw"]["env"])
        self.assertNotIn(rec["kw"]["env"]["FRIDAY_TTS_OUT"], " ".join(rec["argv"]))

    def test_secrets_are_not_passed_to_the_child(self):
        os.environ["FRIDAY_SECRET_ELEVENLABS_API_KEY"] = "leak-me"
        try:
            rec: dict = {}
            LocalSynth(platform="linux", runner=self.runner(rec, self.wav(), "linux"), which=lambda n: "/bin/espeak-ng").synth("hi")
            self.assertNotIn("FRIDAY_SECRET_ELEVENLABS_API_KEY", rec["kw"]["env"])
        finally:
            del os.environ["FRIDAY_SECRET_ELEVENLABS_API_KEY"]

    def test_unavailable_and_failing(self):
        s = LocalSynth(platform="linux", which=lambda n: None)
        self.assertIn("espeak", s.available())
        with self.assertRaises(TTSError):
            s.synth("hi")
        bad = LocalSynth(platform="linux", runner=lambda argv, **kw: SimpleNamespace(returncode=2, stdout=b""), which=lambda n: "/bin/espeak-ng")
        with self.assertRaises(TTSError):
            bad.synth("hi")

    def test_stereo_wav_is_reduced_to_mono(self):
        a = wav_to_audio(self.wav(channels=2, n=100))
        self.assertEqual(len(a.pcm), 200)
        with self.assertRaises(TTSError):
            wav_to_audio(b"not a wav")


class CacheAndEngineTests(TempDirCase):
    def test_cache_roundtrip_and_lru_eviction(self):
        c = TTSCache(self.tmp / "c", max_bytes=2 * len(audio_to_wav(Audio(b"\x01\x00" * 1000, 16000))) + 10)
        for i in range(3):
            c.put(c.key("e", "v", f"phrase {i}"), Audio(b"\x01\x00" * 1000, 16000))
            time.sleep(0.02)
        self.assertEqual(len(list((self.tmp / "c").glob("*.wav"))), 2)
        self.assertIsNone(c.get(c.key("e", "v", "phrase 0")))             # the oldest went first
        self.assertEqual(c.get(c.key("e", "v", "phrase 2")), Audio(b"\x01\x00" * 1000, 16000))
        self.assertIsNone(c.get("zzz"))

    def test_only_fixed_short_phrases_are_cached_replies_are_not(self):
        synth = FakeSynth()
        eng = SpeechEngine([synth], TTSCache(self.tmp / "c"))
        eng.synth("Yes, Alpha?", cacheable=True)
        eng.synth("Yes, Alpha?", cacheable=True)
        self.assertEqual(synth.texts, ["Yes, Alpha?"])                    # second one came from disk
        eng.synth("Your balance is private.")
        eng.synth("Your balance is private.")
        self.assertEqual(len(synth.texts), 3)
        self.assertEqual(len(list((self.tmp / "c").glob("*.wav"))), 1)
        eng.synth("x" * 400, cacheable=True)                              # too long to be a canned phrase
        self.assertEqual(len(list((self.tmp / "c").glob("*.wav"))), 1)

    def test_falls_back_to_the_next_engine_and_reports_why_once(self):
        warnings = []

        class Bad:
            name = "elevenlabs"

            def available(self):
                return None

            def synth(self, text):
                raise TTSError("HTTP 503")

        good = FakeSynth()
        eng = SpeechEngine([Bad(), good], None, on_warning=warnings.append)
        self.assertEqual(eng.synth("a").rate, 16000)
        eng.synth("b")
        self.assertEqual(good.texts, ["a", "b"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("503", warnings[0])

    def test_auth_error_then_fallback_and_no_engine(self):
        class Rejected:
            name = "elevenlabs"

            def available(self):
                return None

            def synth(self, text):
                raise TTSAuthError("key rejected")

        eng = SpeechEngine([Rejected(), FakeSynth()], None)
        eng.synth("a")
        with self.assertRaises(TTSError):
            SpeechEngine([Rejected()], None).synth("a")
        with self.assertRaises(TTSError):
            SpeechEngine([], None).synth("a")


# --------------------------------------------------------------------------- speaker / player
class SpeakerTests(AsyncTempDirCase):
    def make(self):
        synth, player = FakeSynth(), FakePlayer()
        busy: list[bool] = []
        speaker = Speaker(SpeechEngine([synth]), player, on_busy=busy.append)
        return speaker, synth, player, busy

    async def test_speaks_in_order_and_tracks_busy(self):
        speaker, synth, player, busy = self.make()
        self.assertFalse(speaker.busy)
        r = await asyncio.gather(speaker.say("one"), speaker.say("two"))
        self.assertEqual([x.status for x in r], ["done", "done"])
        self.assertEqual(synth.texts, ["one", "two"])
        self.assertFalse(speaker.busy)
        self.assertTrue(busy[0] and not busy[-1])          # (there may be a momentary gap between two queued items)
        self.assertGreater(speaker.last_end, 0)
        self.assertEqual((await speaker.say("   ")).status, "empty")

    async def test_interrupt_stops_playback_and_cancels_the_queue(self):
        speaker, synth, player, busy = self.make()
        player.block = threading.Event()
        a = asyncio.ensure_future(speaker.say("long sentence"))
        b = asyncio.ensure_future(speaker.say("queued behind it"))
        await asyncio.sleep(0.05)
        self.assertTrue(speaker.busy)
        threading.Thread(target=speaker.interrupt).start()               # from another thread, like the wake engine
        self.assertEqual((await a).status, "interrupted")
        self.assertEqual((await b).status, "interrupted")
        self.assertEqual(synth.texts, ["long sentence"])                 # the queued one was never even synthesised
        self.assertFalse(speaker.busy)
        player.block = None
        self.assertEqual((await speaker.say("fresh")).status, "done")     # speech works again afterwards

    async def test_tts_failure_is_reported_not_raised(self):
        speaker, synth, player, busy = self.make()
        synth.fail = True
        self.assertEqual((await speaker.say("hi")).status, "failed")
        self.assertFalse(speaker.busy)


class PlayerTests(unittest.TestCase):
    DEVS = [{"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2}]

    def test_plays_in_chunks_then_drains(self):
        sd = FakeSd(self.DEVS)
        ok = SoundDevicePlayer("", sd=sd).play(Audio(b"\x01\x00" * 24000, 24000), threading.Event())
        self.assertTrue(ok)
        s = sd.streams[0]
        self.assertEqual(len(s.written), 48000)
        self.assertTrue(s.stopped and not s.aborted)

    def test_stop_flag_aborts_mid_playback(self):
        sd = FakeSd(self.DEVS)
        stop = threading.Event()
        stop.set()
        self.assertFalse(SoundDevicePlayer("", sd=sd).play(Audio(b"\x01\x00" * 24000, 24000), stop))
        self.assertTrue(sd.streams[0].aborted)

    def test_unknown_output_device_is_a_clean_error(self):
        with self.assertRaises(AudioDeviceError):
            SoundDevicePlayer("nonexistent", sd=FakeSd(self.DEVS)).play(Audio(b"\x00\x00", 16000), threading.Event())


# --------------------------------------------------------------------------- models
class ModelTests(TempDirCase):
    def cfg(self):
        c = Config()
        c.data_dir = self.tmp
        return c

    def zip_bytes(self, files, symlink=None):
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            for name, data in files.items():
                zf.writestr(name, data)
            if symlink:
                info = zipfile.ZipInfo(symlink)
                info.external_attr = (0o120777) << 16
                zf.writestr(info, "/etc/passwd")
        return bio.getvalue()

    def test_paths(self):
        c = self.cfg()
        self.assertEqual(mdl.vosk_model_path(c), self.tmp / "models" / "vosk-model-small-en-us-0.15")
        self.assertEqual(mdl.whisper_model_path(c), self.tmp / "models" / "faster-whisper-small.en")
        c.voice.stt_model = str(self.tmp / "mine")
        self.assertEqual(mdl.whisper_model_path(c), self.tmp / "mine")

    def test_unzip_refuses_traversal_absolute_symlinks_and_bombs(self):
        for name in ("../evil.txt", "a/../../evil.txt", "/abs.txt", "C:/win.txt", "..\\evil.txt"):
            with zipfile.ZipFile(io.BytesIO(self.zip_bytes({name: "x"}))) as zf, self.assertRaises(mdl.ModelError, msg=name):
                mdl.safe_extract(zf, self.tmp / "out")
        with zipfile.ZipFile(io.BytesIO(self.zip_bytes({"ok.txt": "x"}, symlink="link"))) as zf, self.assertRaises(mdl.ModelError):
            mdl.safe_extract(zf, self.tmp / "out2")
        with zipfile.ZipFile(io.BytesIO(self.zip_bytes({"big.bin": "x" * 5000}))) as zf, self.assertRaises(mdl.ModelError):
            mdl.safe_extract(zf, self.tmp / "out3", max_total=1000)
        with zipfile.ZipFile(io.BytesIO(self.zip_bytes({f"f{i}": "x" for i in range(20)}))) as zf, self.assertRaises(mdl.ModelError):
            mdl.safe_extract(zf, self.tmp / "out4", max_entries=10)
        self.assertFalse((self.tmp / "evil.txt").exists())

    def opener(self, data):
        return lambda req, timeout: FakeResp(data) if True else None

    def test_fetch_vosk_installs_and_prints_the_hash(self):
        data = self.zip_bytes({"vosk-model-small-en-us-0.15/am/final.mdl": "m", "vosk-model-small-en-us-0.15/conf/model.conf": "c"})
        c = self.cfg()
        lines: list[str] = []
        path = mdl.fetch_vosk(c, lines.append, opener=lambda r, t: FakeResp(data))
        self.assertTrue((path / "am" / "final.mdl").is_file())
        self.assertTrue(any(hashlib.sha256(data).hexdigest() in line for line in lines))
        self.assertEqual([p.name for p in (self.tmp / "models").iterdir()], ["vosk-model-small-en-us-0.15"])   # no temp leftovers
        again: list[str] = []
        mdl.fetch_vosk(c, again.append, opener=lambda r, t: (_ for _ in ()).throw(AssertionError("must not download twice")))
        self.assertIn("already present", again[0])

    def test_pin_mismatch_discards_the_download(self):
        data = self.zip_bytes({"m/am/x": "1"})
        c = self.cfg()
        c.voice.vosk_model_sha256 = "0" * 64
        with self.assertRaises(mdl.ModelError) as cm:
            mdl.fetch_vosk(c, lambda s: None, opener=lambda r, t: FakeResp(data))
        self.assertIn("mismatch", str(cm.exception))
        self.assertFalse(mdl.vosk_model_path(c).exists())
        self.assertEqual(list((self.tmp / "models").iterdir()), [])
        c.voice.vosk_model_sha256 = hashlib.sha256(data).hexdigest()
        mdl.fetch_vosk(c, lambda s: None, opener=lambda r, t: FakeResp(data))
        self.assertTrue(mdl.vosk_model_path(c).is_dir())

    def test_http_url_and_non_model_archives_are_refused(self):
        c = self.cfg()
        c.voice.vosk_model_url = "http://alphacephei.com/vosk/models/x.zip"
        with self.assertRaises(mdl.ModelError):
            mdl.fetch_vosk(c, lambda s: None, opener=lambda r, t: FakeResp(b""))
        c.voice.vosk_model_url = "https://example.com/vosk-model-x.zip"
        with self.assertRaises(mdl.ModelError):
            mdl.fetch_vosk(c, lambda s: None, opener=lambda r, t: FakeResp(self.zip_bytes({"readme.txt": "hi"})))
        with self.assertRaises(mdl.ModelError):
            mdl.fetch_vosk(c, lambda s: None, opener=lambda r, t: FakeResp(b"not a zip"))

    def test_download_size_cap(self):
        c = self.cfg()
        old = mdl.MAX_ZIP_BYTES
        mdl.MAX_ZIP_BYTES = 100
        try:
            with self.assertRaises(mdl.ModelError):
                mdl.fetch_vosk(c, lambda s: None, opener=lambda r, t: FakeResp(b"x" * 1000))
        finally:
            mdl.MAX_ZIP_BYTES = old

    def test_fetch_whisper_uses_the_downloader(self):
        c = self.cfg()
        calls = []

        def downloader(size, output_dir=None):
            calls.append((size, output_dir))
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / "model.bin").write_bytes(b"x")

        p = mdl.fetch_whisper(c, lambda s: None, downloader=downloader)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "small.en")
        self.assertNotEqual(calls[0][1], str(p))                         # downloaded to a temp folder, then moved into place
        self.assertTrue((p / "model.bin").is_file())
        self.assertEqual([x.name for x in p.parent.iterdir()], [p.name])  # no temp folder left behind
        mdl.fetch_whisper(c, lambda s: None, downloader=lambda *a, **k: self.fail("downloaded twice"))
        c2 = self.cfg()
        c2.voice.stt_model = str(self.tmp / "other")
        with self.assertRaises(mdl.ModelError):
            mdl.fetch_whisper(c2, lambda s: None, downloader=lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))

    def test_an_incomplete_whisper_download_is_not_installed(self):
        c = self.cfg()

        def bad(size, output_dir=None):
            Path(output_dir).mkdir(parents=True, exist_ok=True)       # no model.bin

        with self.assertRaises(mdl.ModelError):
            mdl.fetch_whisper(c, lambda s: None, downloader=bad)
        self.assertFalse(mdl.whisper_model_path(c).exists())
        self.assertEqual(list(mdl.models_dir(c).iterdir()), [])        # and the temp folder is gone

    def test_a_half_downloaded_model_folder_counts_as_missing(self):
        c = self.cfg()
        target = mdl.whisper_model_path(c)
        target.mkdir(parents=True)
        (target / "config.json").write_text("{}")
        self.assertFalse(mdl.whisper_ready(target))

    def test_force_will_not_delete_a_folder_outside_the_models_dir(self):
        c = self.cfg()
        mine = self.tmp / "my-vosk"
        (mine / "am").mkdir(parents=True)
        c.voice.wake_model = str(mine)
        with self.assertRaises(mdl.ModelError):
            mdl.fetch_vosk(c, lambda s: None, opener=lambda *a, **k: self.fail("must not download"), force=True)
        self.assertTrue((mine / "am").is_dir())

    def test_redirects_to_plain_http_are_refused(self):
        h = mdl._HttpsOnlyRedirects()
        req = urllib.request.Request("https://example.com/m.zip")
        with self.assertRaises(urllib.error.URLError):
            h.redirect_request(req, None, 302, "Found", {}, "http://evil.example/m.zip")


# --------------------------------------------------------------------------- readback built by code
class ReadbackTests(unittest.TestCase):
    def dec(self, tier=RiskTier.T2, reasons=(), paths=()):
        return Decision("confirm", tier, tuple(reasons), resolved_paths=tuple(paths))   # type: ignore[arg-type]

    def test_readback_names_the_action_and_arguments(self):
        t = render_readback("send_msg", {"to": "bob", "body": "see you at 5"}, self.dec(), lambda s: s)
        self.assertIn("send msg", t)
        self.assertIn("to: bob", t)
        self.assertIn("body: see you at 5", t)

    def test_secrets_are_redacted_and_control_characters_dropped(self):
        t = render_readback("fs_write", {"content": "key sk-ABCDEFGHIJKLMNOPQRSTUV\u202e\nline two"}, self.dec(), lambda s: s.replace("sk-ABCDEFGHIJKLMNOPQRSTUV", "[REDACTED]"))
        self.assertNotIn("sk-", t)
        self.assertNotIn("\u202e", t)
        self.assertNotIn("\n", t)

    def test_long_values_and_many_arguments_are_shortened(self):
        t = render_readback("x", {f"k{i}": "v" * 300 for i in range(7)}, self.dec(), lambda s: s)
        self.assertLess(len(t), 700)
        self.assertIn("3 more details that are only on screen", t)

    def test_paths_and_reasons_are_included(self):
        t = render_readback("fs_delete", {"path": "~/old.txt"}, self.dec(RiskTier.T3, ["this turn read untrusted content"], ["C:\\Users\\a\\old.txt"]), lambda s: s)
        self.assertIn("old.txt", t)
        self.assertIn("untrusted", t)

    def test_a_short_complete_readback_is_flagged_complete(self):
        text, complete = build_readback("send_msg", {"to": "bob", "body": "see you at 5"}, self.dec(), lambda s: s)
        self.assertTrue(complete)
        self.assertIn("see you at 5", text)

    def test_anything_left_out_makes_the_readback_incomplete(self):
        d = self.dec()
        cases = {
            "five arguments": {f"k{i}": "v" for i in range(5)},
            "long value": {"body": "word " * 60},
            "long list": {"to": ["a", "b", "c", "d"]},
            "nested dict": {"opts": {"force": True}},
            "long list item": {"to": ["x" * 90]},
        }
        for name, args in cases.items():
            with self.subTest(name):
                self.assertFalse(build_readback("t", args, d, lambda s: s)[1])

    def test_many_resolved_paths_or_a_long_reason_are_incomplete(self):
        self.assertFalse(build_readback("t", {}, self.dec(paths=["/a/1", "/a/2", "/a/3"]), lambda s: s)[1])
        self.assertFalse(build_readback("t", {}, self.dec(reasons=["because " * 40]), lambda s: s)[1])

    def test_a_url_host_is_kept_verbatim_so_the_listener_hears_where_it_goes(self):
        t, complete = build_readback("web_fetch", {"url": "https://evil.example.com/x"}, self.dec(), lambda s: s)
        self.assertIn("evil.example.com", t)
        self.assertTrue(complete)


# --------------------------------------------------------------------------- regression tests from the independent review
class ReviewSensorTests(unittest.TestCase):
    def test_espeak_streamed_wav_with_unknown_length_is_readable(self):
        from friday.sensors.tts import _fix_streamed_wav

        w = bytearray(audio_to_wav(Audio(b"\x01\x00" * 8000, 16000)))
        w[4:8] = b"\xff\xff\xff\xff"
        i = w.find(b"data")
        w[i + 4 : i + 8] = b"\xff\xff\xff\xff"
        self.assertAlmostEqual(wav_to_audio(_fix_streamed_wav(bytes(w))).seconds, 0.5, places=2)

    def test_the_system_powershell_is_preferred_by_absolute_path(self):
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            ps = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            ps.parent.mkdir(parents=True)
            ps.write_bytes(b"")
            old = os.environ.get("SystemRoot")
            os.environ["SystemRoot"] = root
            try:
                self.assertEqual(LocalSynth(platform="win32", which=lambda n: "C:\\evil\\powershell.exe")._program(), str(ps))
            finally:
                if old is None:
                    del os.environ["SystemRoot"]
                else:
                    os.environ["SystemRoot"] = old

    def test_nan_and_inf_in_voice_settings_are_refused(self):
        from friday.core.config import Config, ConfigError, _validate

        for field in ("both_window_s", "clap_spike_ratio", "vad_min_rms", "activation_debounce_s"):
            for bad in (float("nan"), float("inf")):
                cfg = Config()
                setattr(cfg.voice, field, bad)
                with self.assertRaises(ConfigError, msg=f"{field}={bad}"):
                    _validate(cfg)

    def test_voice_id_and_format_reject_a_trailing_newline(self):
        e = ElevenLabsSynth("VoiceId12345\n", lambda: "k", opener=lambda r, t: None)
        self.assertIsNotNone(e.available())
        e = ElevenLabsSynth("VoiceId12345", lambda: "k", output_format="pcm_24000\n", opener=lambda r, t: None)
        self.assertIsNotNone(e.available())

    def test_a_malformed_http_response_is_a_tts_error_not_a_crash(self):
        import http.client

        def opener(req, timeout):
            raise http.client.IncompleteRead(b"")

        with self.assertRaises(TTSError):
            ElevenLabsSynth("VoiceId12345", lambda: "k", opener=opener).synth("hello there")

    def test_near_empty_or_truncated_audio_is_refused_and_the_next_engine_is_used(self):
        class Short:
            name = "short"

            def available(self):
                return None

            def synth(self, text):
                return Audio(b"\x01\x00" * 400, 16000)          # 25 ms for a whole sentence

        class Good:
            name = "good"

            def available(self):
                return None

            def synth(self, text):
                return Audio(b"\x01\x00" * 16000 * 5, 16000)

        warned = []
        eng = SpeechEngine([Short(), Good()], on_warning=warned.append)
        out = eng.synth("I would like to run send message to Bob.")
        self.assertGreater(out.seconds, 1)
        self.assertTrue(any("too short" in w for w in warned))
        with self.assertRaises(TTSError):
            SpeechEngine([Short()]).synth("I would like to run send message to Bob.")

    def test_steady_loud_noise_does_not_retrigger_forever(self):
        e = Endpointer()
        starts = 0
        for i in range(3000):                                              # 60 s of a loud fan
            if e.feed(make_frame(0.05, i * FRAME_S)) is not None:
                starts += 1
        self.assertLessEqual(starts, 2)
        # speech clearly above the fan still gets through afterwards
        got = None
        t = 3000 * FRAME_S
        for lvl in [0.4] * 40 + [0.05] * 60:
            got = e.feed(make_frame(lvl, t)) or got
            t += FRAME_S
        self.assertIsNotNone(got)

    def test_a_wake_worker_failure_calls_the_failure_hook(self):
        class Bad:
            def feed(self, pcm):
                raise RuntimeError("model crashed")

        seen = []
        w = WakeWorker(Bad(), lambda e, t: None)
        w._on_failure = seen.append
        w.start()
        w.offer(make_frame(0.1, 0.0))
        deadline = time.time() + 2
        while not seen and time.time() < deadline:
            time.sleep(0.01)
        w.stop()
        self.assertTrue(seen and "model crashed" in seen[0])

    def test_endpointer_reset_and_feed_can_race_without_error(self):
        e = Endpointer()
        stop = threading.Event()
        errors = []

        def feeder():
            i = 0
            try:
                while not stop.is_set():
                    e.feed(make_frame(0.3 if i % 7 < 4 else 0.001, i * FRAME_S))
                    i += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        th = threading.Thread(target=feeder)
        th.start()
        for _ in range(2000):
            e.reset()
        stop.set()
        th.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
