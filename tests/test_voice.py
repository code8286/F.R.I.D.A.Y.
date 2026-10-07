# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""The voice session end to end (fake microphone, fake speech engines, scripted model) and its security properties."""

from __future__ import annotations

import asyncio
import contextlib
import io
import threading

from friday.core.config import Config, load_config
from friday.core.daemon import FridayCore
from friday.core.errors import AdmissionError, ConfigError
from friday.security.policy import Decision
from friday.security.secrets import MemoryBackend, SecretStore
from friday.security.tiers import ConfirmChannel, Gate, RiskTier
from friday.sensors.audio_hub import FRAME_S
from friday.sensors.diagnostics import audio_devices, voice_check
from friday.sensors.stack import build_voice
from friday.sensors.tts import Audio
from friday.sensors.vad import Utterance
from friday.sensors.wakeword import STOP
from tests.helpers import AsyncTempDirCase, TempDirCase, calls, make_cfg, make_rig, say, use
from tests.test_sensors import DeviceTests, FakeSd
from tests.voice_helpers import make_frame, make_voice


class VoiceCase(AsyncTempDirCase):
    async def rig(self, script, **overrides):
        rig = await make_rig(self.tmp, script, mutate=overrides.pop("mutate", None))
        self.addAsyncCleanup(rig.core.stop)
        v = await make_voice(rig.core, **overrides)
        self.addAsyncCleanup(v.channel.stop)
        return rig, v

    async def challenge_of(self, rig):
        return next(iter(rig.core.broker.pending())).challenge


# --------------------------------------------------------------------------- session basics
class SessionTests(VoiceCase):
    async def test_activation_opens_a_window_and_greets_by_name(self):
        rig, v = await self.rig([])
        self.assertFalse(v.channel.session_active)
        await v.activate(("clap",))
        self.assertTrue(v.channel.session_active)
        await v.until(lambda: v.spoken == ["Yes, Alpha?"])
        events = [r.event for r in rig.core.audit.tail(10)]
        self.assertIn("voice.activated", events)

    async def test_a_spoken_command_becomes_a_turn_and_the_reply_is_spoken(self):
        rig, v = await self.rig([say("It is half past three.")])
        await v.activate()
        await v.hear("what time is it")
        await v.until(lambda: "It is half past three." in v.spoken)
        first = rig.core.sessions.main().history[0]
        self.assertEqual(first.text, "what time is it")
        self.assertEqual(first.meta.get("source"), "voice")

    async def test_nothing_is_heard_outside_a_window(self):
        rig, v = await self.rig([say("never")])
        await v.hear("hello?")
        self.assertEqual(v.stt.calls, 0)
        self.assertEqual(rig.core.sessions.main().history, [])
        with self.assertRaises(AdmissionError):
            await rig.core.submit("hello", "voice")           # the core itself refuses voice input with no window

    async def test_wake_phrase_echo_is_not_a_command(self):
        rig, v = await self.rig([say("Half past three.")])
        await v.activate()
        await v.hear("Friday wake up")
        self.assertEqual(rig.core.sessions.main().history, [])
        await v.hear("friday wake up what time is it")
        await v.until(lambda: "Half past three." in v.spoken)
        self.assertEqual(rig.core.sessions.main().history[0].text, "what time is it")

    async def test_filler_and_empty_transcripts_are_ignored(self):
        rig, v = await self.rig([])
        await v.activate()
        for junk in ("", "um", "...", "you"):
            await v.hear(junk)
        self.assertEqual(rig.core.sessions.main().history, [])

    async def test_window_closes_when_idle(self):
        rig, v = await self.rig([])
        await v.activate()
        await v.until(lambda: not v.player.started.is_set() or True)
        await v.settle()
        v.clock.advance(10)
        await v.settle()
        self.assertTrue(v.channel.session_active)
        v.clock.advance(15)
        await v.until(lambda: not v.channel.session_active)

    async def test_reply_is_redacted_before_it_reaches_the_tts_provider_and_made_speakable(self):
        rig, v = await self.rig([say("Your key is sk-ABCDEFGHIJKLMNOPQRSTUV, see **https://example.com/a**.\n```\nsecret code\n```")])
        await v.activate()
        await v.hear("what is my key")
        await v.until(lambda: len(v.spoken) >= 2)
        text = v.spoken[1]
        self.assertNotIn("sk-", text)
        self.assertIn("[REDACTED]", text)
        self.assertNotIn("http", text)
        self.assertNotIn("secret code", text)

    async def test_long_replies_are_cut_to_a_sentence(self):
        rig, v = await self.rig([say("A sentence that goes on. " * 100)], max_spoken_chars=120)
        await v.activate()
        await v.hear("tell me a lot")
        await v.until(lambda: len(v.spoken) >= 2)
        self.assertLessEqual(len(v.spoken[1]), 160)
        self.assertTrue(v.spoken[1].endswith("The rest is on screen."))

    async def test_input_mode_line_is_in_the_system_prompt_only_during_a_window(self):
        rig, v = await self.rig([])
        self.assertNotIn("Input mode", rig.core.context.system_prompt())
        await v.activate()
        self.assertIn("Input mode: voice", rig.core.context.system_prompt())

    async def test_a_second_utterance_while_a_turn_runs_is_queued_not_lost(self):
        rig, v = await self.rig([say("first answer"), say("second answer")])
        await v.activate()
        await v.hear("one")
        await v.hear("two")
        await v.until(lambda: "second answer" in v.spoken)
        self.assertLess(v.spoken.index("first answer"), v.spoken.index("second answer"))

    async def test_speech_failure_never_breaks_the_session(self):
        rig, v = await self.rig([say("answer")])
        v.synth.fail = True
        await v.activate()
        await v.hear("hello")
        await v.until(lambda: any(m.role == "assistant" for m in rig.core.sessions.main().history))
        self.assertTrue(v.channel.session_active)


# --------------------------------------------------------------------------- spoken confirmations
class ConfirmationTests(VoiceCase):
    async def test_t2_voice_approval_needs_a_readback_then_a_yes(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "see you at five"})), say("Sent it.")])
        await v.activate()
        await v.hear("message bob")
        await v.until(lambda: any("send msg" in t for t in v.spoken))
        readback = next(t for t in v.spoken if "send msg" in t)
        self.assertIn("to: bob", readback)
        self.assertIn("see you at five", readback)
        self.assertIn("Say yes to approve", readback)
        self.assertEqual(rig.ran, [])                                    # nothing ran on the readback alone
        await v.until(lambda: v.channel._reqs and all(r.readback_ok for r in v.channel._reqs.values()))
        await v.hear("yes")
        await v.until(lambda: "Sent it." in v.spoken)
        self.assertEqual(rig.ran, [("send_msg", {"to": "bob", "body": "see you at five"})])
        self.assertIn("Approved.", v.spoken)

    async def test_a_yes_before_the_readback_has_finished_is_not_an_approval(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "hi"})), say("Sent it.")])
        v.player.block = threading.Event()                               # the readback is still being spoken
        await v.activate()
        v.player.block.set()
        await v.until(lambda: v.channel.session_active and v.spoken)
        v.player.block = threading.Event()
        await v.hear("message bob")
        await v.until(lambda: v.channel._reqs)
        await v.settle()
        await v.hear("yes")                                              # arrives while the readback is mid-sentence
        self.assertEqual(rig.ran, [])
        self.assertEqual(len(rig.core.broker.pending()), 1)
        v.player.block.set()                                             # readback finishes
        await v.until(lambda: v.channel._reqs and all(r.readback_ok for r in v.channel._reqs.values()))
        self.assertIn("Let me read that again.", v.spoken)
        await v.hear("yes")
        await v.until(lambda: rig.ran)

    async def test_an_interrupted_readback_cannot_be_approved(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "hi"})), say("ok")], barge_in="stop")
        await v.activate()
        await v.settle()
        v.player.block = threading.Event()
        await v.hear("message bob")
        await v.until(lambda: v.player.started.is_set() and v.channel._reqs)
        v.channel._on_wake_event(STOP, 0.0)                              # "stop!" cuts the readback off
        await v.until(lambda: not v.channel.speaker.busy)
        self.assertFalse(next(iter(v.channel._reqs.values())).readback_ok)
        v.player.block = None
        await v.hear("yes")
        self.assertEqual(rig.ran, [])

    async def test_t3_needs_the_challenge_phrase_which_is_never_spoken(self):
        rig, v = await self.rig([calls(use("wipe")), say("Wiped.")])
        seen = []
        rig.core.bus.on("confirm.requested", lambda ev: seen.append(ev.payload))
        await v.activate()
        await v.hear("wipe everything")
        await v.until(lambda: any("challenge phrase" in t for t in v.spoken))
        challenge = seen[0]["challenge"]
        self.assertEqual(len(challenge.split()), 3)
        for word in challenge.split():
            self.assertNotIn(word, " ".join(v.spoken).lower().split(), "the challenge phrase must never be spoken")
        await v.hear("yes")
        self.assertEqual(rig.ran, [])
        await v.until(lambda: any("challenge phrase shown on screen" in t for t in v.spoken))
        await v.hear("yes yes please do it")
        self.assertEqual(rig.ran, [])
        await v.hear(f"the phrase is {challenge}")
        await v.until(lambda: rig.ran)
        self.assertEqual(rig.ran, [("wipe", {})])

    async def test_no_cancels(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "hi"})), say("Okay, not sending.")])
        await v.activate()
        await v.hear("message bob")
        await v.until(lambda: v.channel._reqs and all(r.readback_ok for r in v.channel._reqs.values()))
        await v.hear("no, cancel that")
        await v.until(lambda: "Okay, not sending." in v.spoken)
        self.assertEqual(rig.ran, [])
        self.assertIn("Cancelled.", v.spoken)

    async def test_only_a_short_clean_yes_counts(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "hi"})), say("Sent.")])
        await v.activate()
        await v.hear("message bob")
        await v.until(lambda: v.channel._reqs and all(r.readback_ok for r in v.channel._reqs.values()))
        await v.hear("yes yes yes yes yes yes")                          # a long run of words, e.g. from a TV
        await v.hear("well maybe, who knows, but yes")
        await v.hear("what is the weather")                              # chatter is not an answer either
        self.assertEqual(rig.ran, [])
        self.assertEqual(len(rig.core.broker.pending()), 1)
        await v.hear("yes")
        await v.until(lambda: rig.ran)

    async def test_requests_not_raised_by_a_voice_turn_cannot_be_approved_by_voice(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "mallory", "body": "x"})), say("typed turn done"), say("a fresh voice turn")])
        await v.activate()
        await v.settle()
        typed = asyncio.ensure_future(rig.core.submit("send it", "console"))
        await v.until(lambda: rig.core.broker.pending())
        spoken_before = len(v.spoken)
        await v.settle()
        self.assertEqual(len(v.spoken), spoken_before)                  # never read out
        await v.hear("yes")                                              # an ordinary voice command, queued behind the typed turn...
        await v.settle()
        self.assertEqual(rig.ran, [])                                    # ...and it approved nothing
        self.assertEqual(len(rig.core.broker.pending()), 1)
        rig.core.respond_confirmation(rig.core.broker.pending()[0].id, False, ConfirmChannel.TYPED, text="no")
        await typed
        await v.until(lambda: "a fresh voice turn" in v.spoken)
        self.assertEqual(rig.ran, [])

    async def test_an_unanswered_request_is_reported_as_timed_out(self):
        def short(cfg: Config) -> None:
            cfg.security.confirm_ttl_s = 0.3

        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "hi"})), say("It timed out.")], mutate=short)
        await v.activate()
        await v.hear("message bob")
        await v.until(lambda: "That request timed out." in v.spoken, timeout=5)
        await v.until(lambda: "It timed out." in v.spoken)
        self.assertEqual(rig.ran, [])

    async def test_the_window_stays_open_while_an_approval_is_waiting(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "hi"})), say("ok")])
        await v.activate()
        await v.hear("message bob")
        await v.until(lambda: v.channel._reqs and all(r.readback_ok for r in v.channel._reqs.values()))
        v.clock.advance(120)
        await v.settle()
        self.assertTrue(v.channel.session_active)
        rig.core.respond_confirmation(rig.core.broker.pending()[0].id, False, ConfirmChannel.TYPED, text="no")

    async def test_waking_never_answers_an_approval(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "hi"})), say("ok")])
        await v.activate()
        await v.hear("message bob")
        await v.until(lambda: v.channel._reqs and all(r.readback_ok for r in v.channel._reqs.values()))
        v.clock.advance(5)
        await v.activate(("wake",))                                      # clap or "friday wake up" again
        self.assertEqual(rig.ran, [])
        self.assertEqual(len(rig.core.broker.pending()), 1)
        rig.core.respond_confirmation(rig.core.broker.pending()[0].id, False, ConfirmChannel.TYPED, text="no")


# --------------------------------------------------------------------------- the broker's own voice rules
class BrokerVoiceTests(AsyncTempDirCase):
    async def request(self, tier=RiskTier.T2):
        rig = await make_rig(self.tmp, [])
        self.addAsyncCleanup(rig.core.stop)
        req = rig.core.broker.create(session_id="main", tool="send_msg", args={"to": "bob"}, decision=Decision(Gate.CONFIRM, tier, ("r",)))
        return rig, req

    def voice(self, rig, req, text, readback=True):
        return rig.core.respond_confirmation(req.id, True, ConfirmChannel.VOICE, text=text, readback_confirmed=readback, voice_session_active=True)

    async def test_readback_is_in_the_event_payload_and_never_holds_the_challenge(self):
        rig = await make_rig(self.tmp, [])
        self.addAsyncCleanup(rig.core.stop)
        seen = []
        rig.core.bus.on("confirm.requested", lambda ev: seen.append(ev.payload))
        rig.core.broker.create(session_id="main", tool="wipe", args={}, decision=Decision(Gate.CONFIRM, RiskTier.T3, ("r",)))
        p = seen[0]
        self.assertTrue(p["readback"].startswith("I would like to run wipe"))
        for word in p["challenge"].split():
            self.assertNotIn(word, p["readback"].lower().split())

    async def test_t2_yes_rules(self):
        rig, req = await self.request()
        self.assertFalse(self.voice(rig, req, "yes yes yes yes yes yes").ok)       # too many words
        self.assertFalse(self.voice(rig, req, "yes but not really").ok)            # refusal word
        self.assertFalse(self.voice(rig, req, "I said yes to the cake earlier").ok)
        self.assertFalse(self.voice(rig, req, "yes", readback=False).ok)           # no readback yet
        self.assertFalse(rig.core.respond_confirmation(req.id, True, ConfirmChannel.VOICE, text="yes", readback_confirmed=True, voice_session_active=False).ok)
        self.assertTrue(self.voice(rig, req, "Yes.").ok)
        self.assertFalse(self.voice(rig, req, "yes").ok)                           # single use

    async def test_t3_voice_yes_is_never_enough(self):
        rig, req = await self.request(RiskTier.T3)
        self.assertFalse(self.voice(rig, req, "yes").ok)
        self.assertFalse(self.voice(rig, req, "approve confirm yes absolutely").ok)
        wrong = "amber anchor apple" if req.challenge != "amber anchor apple" else "bolt breeze bronze"
        self.assertFalse(self.voice(rig, req, wrong).ok)
        self.assertTrue(self.voice(rig, req, f"okay {req.challenge}").ok)


# --------------------------------------------------------------------------- recorder gating / half duplex
class GatingTests(VoiceCase):
    def feed(self, v, levels, t0=0.0):
        t = t0
        for lvl in levels:
            v.channel._on_frame(make_frame(lvl, t))
            t += FRAME_S
        return t

    async def test_the_recorder_hears_you_once_the_window_is_open_and_quiet(self):
        rig, v = await self.rig([say("Hello yourself.")])
        await v.activate()
        await v.until(lambda: v.spoken)                                  # greeting finished
        v.clock.advance(2.0)                                             # past the post-activation and echo guards
        v.stt.say("hello friday")
        self.feed(v, [0.001] * 50 + [0.06] * 30 + [0.001] * 50)
        await v.until(lambda: "Hello yourself." in v.spoken)
        self.assertEqual(v.stt.calls, 1)

    async def test_nothing_is_recorded_while_friday_is_speaking_or_just_after(self):
        rig, v = await self.rig([say("ok")])
        await v.activate()
        await v.until(lambda: v.spoken)
        v.clock.advance(2.0)
        v.player.block = threading.Event()
        speaking = asyncio.ensure_future(v.channel._say("A long reply that is still being spoken."))
        await v.until(lambda: v.channel.speaker.busy)
        self.feed(v, [0.001] * 50 + [0.06] * 30 + [0.001] * 50)         # her own voice coming back through the mic
        await v.settle()
        self.assertEqual(v.stt.calls, 0)
        v.player.block.set()
        await speaking
        v.clock.advance(0.2)                                             # inside the 450 ms echo guard
        self.feed(v, [0.001] * 50 + [0.06] * 30 + [0.001] * 50)
        await v.settle()
        self.assertEqual(v.stt.calls, 0)
        v.clock.advance(1.0)
        v.stt.say("hello")
        self.feed(v, [0.001] * 50 + [0.06] * 30 + [0.001] * 50)
        await v.until(lambda: v.stt.calls == 1)

    async def test_the_recorder_is_off_with_no_window_and_with_the_kill_switch(self):
        rig, v = await self.rig([])
        self.feed(v, [0.001] * 50 + [0.06] * 30 + [0.001] * 50)
        await v.settle()
        self.assertEqual(v.stt.calls, 0)
        await v.activate()
        v.clock.advance(5)
        rig.core.trip_kill("test", "test")
        self.feed(v, [0.001] * 50 + [0.06] * 30 + [0.001] * 50)
        await v.settle()
        self.assertEqual(v.stt.calls, 0)

    async def test_double_clap_in_the_frames_opens_a_window(self):
        rig, v = await self.rig([])
        levels = [0.001] * 100 + [0.2, 0.05] + [0.001] * 8 + [0.2, 0.05] + [0.001] * 20
        self.feed(v, levels)
        await v.until(lambda: v.channel.session_active)
        self.assertIn("voice.activated", [r.event for r in rig.core.audit.tail(10)])

    async def test_clap_while_speaking_is_a_barge_in(self):
        rig, v = await self.rig([], barge_in="any")
        await v.activate()
        await v.until(lambda: v.spoken)
        v.clock.advance(10)
        v.player.block = threading.Event()
        talking = asyncio.ensure_future(v.channel._say("Talking for a while now."))
        await v.until(lambda: v.channel.speaker.busy)
        await v.activate(("clap",))
        await v.until(lambda: not v.channel.speaker.busy)
        self.assertEqual((await talking), "interrupted")


# --------------------------------------------------------------------------- kill switch, reminders
class KillAndReminderTests(VoiceCase):
    async def test_her_own_voice_cannot_cut_her_off_by_default(self):
        rig, v = await self.rig([])
        await v.activate()
        await v.until(lambda: v.spoken)
        v.clock.advance(10)
        v.player.block = threading.Event()
        talking = asyncio.ensure_future(v.channel._say("Talking for a while now."))
        await v.until(lambda: v.channel.speaker.busy)
        v.channel._on_wake_event(STOP, 0.0)
        await v.activate(("clap",))
        self.assertTrue(v.channel.speaker.busy)
        v.player.block.set()
        self.assertEqual(await talking, "done")

    async def test_voice_is_off_until_asked_and_the_console_reports_it(self):
        import io

        from friday.channels.console import ConsoleChannel

        rig = await make_rig(self.tmp, [])
        self.addAsyncCleanup(rig.core.stop)
        self.assertIsNone(rig.core.voice)
        out = io.StringIO()
        con = ConsoleChannel(rig.core, out=out)
        await con._command("/voice")
        await con._command("/voice off")
        self.assertIn("voice is off", out.getvalue())
        self.assertIn("already off", out.getvalue())

    async def test_kill_switch_silences_closes_and_refuses_reactivation(self):
        rig, v = await self.rig([say("never said")])
        v.player.block = threading.Event()
        await v.activate()
        await v.until(lambda: v.player.started.is_set())
        rig.core.trip_kill("test", "test")
        await v.until(lambda: not v.channel.session_active and not v.channel.speaker.busy)
        v.clock.advance(10)
        await v.activate()
        self.assertFalse(v.channel.session_active)
        self.assertIn("voice.activation_refused", [r.event for r in rig.core.audit.tail(10)])
        rig.core.reset_kill("test")
        v.player.block = None
        v.clock.advance(10)
        await v.activate()
        self.assertTrue(v.channel.session_active)

    async def test_reminders_are_spoken_without_opening_a_window(self):
        rig, v = await self.rig([])
        rig.core.bus.publish("reminder.due", {"id": 1, "message": "stand up and stretch", "late": False})
        await v.until(lambda: v.spoken == ["Reminder: stand up and stretch"])
        rig.core.bus.publish("reminder.due", {"id": 2, "message": "call mum", "late": True})
        await v.until(lambda: "Missed reminder: call mum" in v.spoken)
        self.assertFalse(v.channel.session_active)

    async def test_reminders_can_be_switched_off(self):
        rig, v = await self.rig([], speak_reminders=False)
        rig.core.bus.publish("reminder.due", {"id": 1, "message": "quiet please", "late": False})
        await v.settle()
        self.assertEqual(v.spoken, [])

    async def test_a_reminder_text_is_redacted_before_speech(self):
        rig, v = await self.rig([])
        rig.core.bus.publish("reminder.due", {"id": 1, "message": "rotate sk-ABCDEFGHIJKLMNOPQRSTUV", "late": False})
        await v.until(lambda: v.spoken)
        self.assertNotIn("sk-", v.spoken[0])


# --------------------------------------------------------------------------- building it from configuration
class StackTests(TempDirCase):
    def core(self, **voice):
        cfg = make_cfg(self.tmp)
        cfg.voice.enabled = True
        for k, val in voice.items():
            setattr(cfg.voice, k, val)
        return FridayCore(cfg, secrets=SecretStore(MemoryBackend()))

    def test_voice_is_off_by_default(self):
        core = FridayCore(make_cfg(self.tmp), secrets=SecretStore(MemoryBackend()))
        self.assertIsNone(core.voice)
        self.assertEqual([d for d in core.degraded if d.startswith("voice")], [])

    def test_missing_pieces_are_reported_and_the_core_still_starts(self):
        core = self.core()
        self.assertIsNotNone(core.voice)
        text = " | ".join(core.degraded)
        self.assertIn("listening is off", text)
        self.assertIn("speaking is off", text)
        self.assertIsNone(core.voice.hub)                               # no speech model, so the microphone is never opened

        async def go():
            await core.start()
            await core.stop()

        asyncio.run(go())

    def test_with_a_fake_audio_device_and_models_the_mic_hub_and_wake_are_built(self):
        core = self.core()
        sd = FakeSd(DeviceTests.DEVS)
        (self.tmp / "models" / "faster-whisper-small.en").mkdir(parents=True)
        (self.tmp / "models" / "faster-whisper-small.en" / "model.bin").write_bytes(b"x")
        # the transcriber's check() needs the library unless a factory is injected; fake the import
        import sys
        import types

        fake = types.ModuleType("faster_whisper")
        sys.modules["faster_whisper"] = fake
        try:
            channel, notes = build_voice(core, sd=sd)
        finally:
            del sys.modules["faster_whisper"]
        self.assertIsNotNone(channel.hub)
        self.assertIsNotNone(channel.stt)
        self.assertIsNone(channel.wake)                                 # no Vosk model folder
        self.assertTrue(any("wake phrase is off" in n for n in notes))

    def test_tts_none_and_local_choices(self):
        core = self.core(tts_engine="none")
        self.assertTrue(any("speaking is off" in n for n in core.degraded))
        core = self.core(tts_engine="local")
        self.assertEqual([e.name for e in core.voice.speaker.engine.engines], ["local"])
        core = self.core()
        self.assertEqual([e.name for e in core.voice.speaker.engine.engines], ["elevenlabs", "local"])

    def test_the_elevenlabs_key_is_read_from_the_secret_store_not_config(self):
        core = self.core(elevenlabs_voice_id="VoiceId12345")
        el = core.voice.speaker.engine.engines[0]
        self.assertIn("API key", el.available())
        core.secrets.set("elevenlabs_api_key", "xi-test-key-123456")
        self.assertIsNone(el.available())
        self.assertNotIn("xi-test-key-123456", repr(core.cfg.voice))
        self.assertIn("xi-test-key-123456", [v for v in core.redactor._values])     # and it is registered for redaction


class ConfigTests(TempDirCase):
    def load(self, text):
        p = self.tmp / "c.toml"
        p.write_text(text, encoding="utf-8")
        return load_config(str(p))

    def test_defaults_and_overrides(self):
        c = self.load("")
        self.assertFalse(c.voice.enabled)
        c = self.load('[voice]\nenabled = true\nactivation = "wake"\nwake_phrases = ["hey friday"]\nsession_idle_s = 30\n')
        self.assertTrue(c.voice.enabled)
        self.assertEqual((c.voice.activation, c.voice.wake_phrases, c.voice.session_idle_s), ("wake", ["hey friday"], 30.0))

    def test_bad_values_are_rejected(self):
        for body in (
            'activation = "sometimes"', 'tts_engine = "robot"', "session_idle_s = 1", "wake_phrases = []", 'wake_phrases = ["  "]',
            "clap_min_rms = 2", "max_spoken_chars = 5", 'stt_model_size = "../../x"', "echo_guard_ms = -1", "unknown_key = 1",
        ):
            with self.assertRaises(ConfigError, msg=body):
                self.load(f"[voice]\n{body}\n")


# --------------------------------------------------------------------------- command-line helpers
class CliTests(TempDirCase):
    def test_audio_devices_lists_inputs_and_outputs(self):
        lines: list[str] = []
        self.assertEqual(audio_devices(lines.append, sd=FakeSd(DeviceTests.DEVS)), 0)
        text = "\n".join(lines)
        self.assertIn("[0] Built-in Mic   <- default", text)
        self.assertIn("[1] Speakers   <- default", text)
        self.assertIn("[2] USB Headset", text)

    def test_voice_check_without_listening_reports_what_is_missing(self):
        cfg = make_cfg(self.tmp)
        lines: list[str] = []
        secrets = SecretStore(MemoryBackend({"elevenlabs_api_key": "xi-secret-value-9999"}))
        cfg.voice.elevenlabs_voice_id = "VoiceId12345"
        rc = voice_check(cfg, secrets, seconds=0, out=lines.append)
        text = "\n".join(lines)
        self.assertIn("Packages:", text)
        self.assertIn("fetch-models", text)
        self.assertIn("ElevenLabs", text)
        self.assertNotIn("xi-secret-value-9999", text)             # the key is never printed
        self.assertIn("ElevenLabs: ready", text)
        self.assertEqual(rc, 1 if "[!!]" in text else 0)

    def test_fetch_models_is_an_explicit_command_with_clean_errors(self):
        from friday.__main__ import main

        cfg_path = self.tmp / "c.toml"
        cfg_path.write_text(f'data_dir = "{self.tmp.as_posix()}"\n[voice]\nvosk_model_url = "http://insecure.example/x.zip"\n', encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = main(["--config", str(cfg_path), "fetch-models", "vosk"])
        self.assertEqual(rc, 1)
        self.assertIn("https", err.getvalue())
        self.assertFalse((self.tmp / "models").exists())


# --------------------------------------------------------------------------- regression tests from the independent review
class ReviewFixTests(VoiceCase):
    async def ready(self, v):
        await v.until(lambda: v.channel._reqs and all(r.readback_ok or not r.complete for r in v.channel._reqs.values()))

    async def test_a_request_raised_by_a_typed_turn_is_not_voice_owned_even_if_a_voice_turn_is_waiting(self):
        send = lambda to: calls(use("send_msg", {"to": to, "body": "x"}))     # noqa: E731
        rig, v = await self.rig([send("first"), send("second"), say("typed turn done"), say("voice reply")])
        await v.activate()
        await v.settle()
        typed = asyncio.ensure_future(rig.core.submit("do it", "console"))
        await v.until(lambda: rig.core.broker.pending())
        await v.hear("hello there")                                      # a voice turn is now waiting on the session lock
        await v.until(lambda: v.channel._turn_running)
        first = rig.core.broker.pending()[0]
        rig.core.respond_confirmation(first.id, True, ConfirmChannel.TYPED, text="yes")
        await v.until(lambda: any(r.tool == "send_msg" and r.id != first.id for r in rig.core.broker.pending()))
        spoken_before = len(v.spoken)
        await v.settle()
        self.assertEqual(v.channel._reqs, {})                            # the typed turn's second request is not voice-owned
        self.assertEqual(len(v.spoken), spoken_before)                   # and was never read out
        await v.hear("yes")
        await v.settle()
        self.assertEqual(len(rig.core.broker.pending()), 1)              # a spoken yes approved nothing
        rig.core.respond_confirmation(rig.core.broker.pending()[0].id, False, ConfirmChannel.TYPED, text="no")
        await typed

    async def test_the_readback_is_spoken_word_for_word_including_the_url_host(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "see https://evil.example.com/pay now"})), say("ok")])
        await v.activate()
        await v.hear("message bob")
        await self.ready(v)
        said = next(t for t in v.spoken if "send msg" in t)
        self.assertIn("https://evil.example.com/pay", said)              # not "a link", not shortened
        rig.core.respond_confirmation(rig.core.broker.pending()[0].id, False, ConfirmChannel.TYPED, text="no")

    async def test_an_action_too_detailed_to_read_out_can_only_be_approved_on_screen(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "word " * 80})), say("done")])
        await v.activate()
        await v.hear("message bob a long note")
        await v.until(lambda: any("too detailed" in t for t in v.spoken))
        self.assertFalse(any("Say yes to approve" in t for t in v.spoken))
        await v.hear("yes")
        await v.settle()
        self.assertEqual(rig.ran, [])
        self.assertEqual(len(rig.core.broker.pending()), 1)
        req = rig.core.broker.pending()[0]
        res = rig.core.respond_confirmation(req.id, True, ConfirmChannel.VOICE, text="yes", readback_confirmed=True, voice_session_active=True)
        self.assertFalse(res.ok)                                         # the broker refuses it too
        self.assertIn("on screen", res.reason)
        rig.core.respond_confirmation(req.id, True, ConfirmChannel.UI_CLICK)
        await v.until(lambda: rig.ran)

    async def test_speech_that_began_before_the_readback_ended_is_not_an_answer(self):
        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "hi"})), say("Sent.")])
        await v.activate()
        await v.hear("message bob")
        await self.ready(v)
        st = next(iter(v.channel._reqs.values()))
        v.stt.say("yes")
        v.channel._enqueue_utterance(Utterance(b"\x00\x00" * 8000, 0.0, 0.5, "silence"), started=st.readback_end - 2.0)
        await v.settle()
        self.assertEqual(rig.ran, [])
        self.assertIn("voice.stale_answer_ignored", [r.event for r in rig.core.audit.tail(20)])
        await v.hear("yes")                                              # a fresh answer still works
        await v.until(lambda: rig.ran)

    async def test_an_unexpected_error_in_a_loop_does_not_leave_the_channel_deaf(self):
        rig, v = await self.rig([say("I heard you.")])
        real = v.channel._route_confirmation
        calls_seen = []

        def flaky(text, started=None):
            calls_seen.append(text)
            if len(calls_seen) == 1:
                raise RuntimeError("bug in the router")
            return real(text, started)

        v.channel._route_confirmation = flaky                           # type: ignore[method-assign]
        await v.activate()
        await v.hear("first")
        await v.hear("second")
        await v.until(lambda: "I heard you." in v.spoken)
        self.assertEqual(calls_seen, ["first", "second"])

    async def test_an_engine_or_player_crash_is_a_failed_speech_not_an_exception(self):
        rig, v = await self.rig([])

        def boom(*a, **k):
            raise RuntimeError("driver exploded")

        v.channel.speaker.engine.synth = boom                           # type: ignore[method-assign]
        self.assertEqual(await v.channel._say("hello"), "failed")
        v.channel.speaker.engine.synth = lambda *a, **k: Audio(b"\x01\x00" * 16000, 16000)   # type: ignore[method-assign]
        v.player.play = boom                                            # type: ignore[method-assign]
        self.assertEqual(await v.channel._say("hello"), "failed")
        self.assertFalse(v.channel.speaker.busy)

    async def test_nothing_opens_a_window_while_friday_is_speaking_or_just_after(self):
        rig, v = await self.rig([])
        v.player.block = threading.Event()
        talking = asyncio.ensure_future(v.channel._say("A reminder is being read out."))
        await v.until(lambda: v.channel.speaker.busy)
        await v.activate(("wake",))                                      # e.g. the wake phrase heard inside FRIDAY's own speech
        self.assertFalse(v.channel.session_active)
        self.assertIn("voice.activation_refused", [r.event for r in rig.core.audit.tail(10)])
        v.player.block.set()
        await talking
        await v.activate(("clap",))                                      # still inside the echo guard
        self.assertFalse(v.channel.session_active)
        v.clock.advance(2)
        await v.activate(("clap",))
        self.assertTrue(v.channel.session_active)

    async def test_reminders_that_fire_together_are_one_short_announcement(self):
        rig, v = await self.rig([])
        for i in range(5):
            rig.core.bus.publish("reminder.due", {"id": i, "message": f"item {i}", "late": False})
        await v.until(lambda: v.spoken)
        await v.settle()
        self.assertEqual(len(v.spoken), 1)
        self.assertIn("item 0", v.spoken[0])
        self.assertIn("And 2 more on screen.", v.spoken[0])

    async def test_a_reminder_that_arrives_while_another_is_being_spoken_is_not_lost(self):
        rig, v = await self.rig([])
        v.player.block = threading.Event()
        rig.core.bus.publish("reminder.due", {"id": 1, "message": "first", "late": False})
        await v.until(lambda: v.player.started.is_set())
        rig.core.bus.publish("reminder.due", {"id": 2, "message": "second", "late": False})
        await v.settle()
        v.player.block.set()
        await v.until(lambda: any("second" in t for t in v.spoken))

    async def test_a_dead_wake_engine_is_reported_on_screen(self):
        rig, v = await self.rig([])
        seen = []
        rig.core.bus.on("core.warning", lambda ev: seen.append(ev.payload["message"]))
        v.channel._on_wake_failure("RuntimeError: model crashed")
        await v.settle()
        self.assertTrue(any("wake-phrase engine stopped" in m and "clap" in m for m in seen))

    async def test_an_approval_that_expires_while_everyone_is_quiet_is_still_announced(self):
        def short(cfg: Config) -> None:
            cfg.security.confirm_ttl_s = 0.3

        rig, v = await self.rig([calls(use("send_msg", {"to": "bob", "body": "hi"})), say("later")], mutate=short)
        await v.activate()
        await v.hear("message bob")
        await v.until(lambda: "That request timed out." in v.spoken, timeout=5)
