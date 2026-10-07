# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Voice channel: the listening session, spoken replies and voice confirmations (Architecture §2, §6).

Lifecycle
  idle        only the clap detector and the wake engine listen. Nothing is recorded or transcribed.
  activation  a double clap and/or "FRIDAY wake up" opens a listening WINDOW (a voice session) and FRIDAY greets you.
              Waking is not authorization: it grants no privilege and answers no approval.
  listening   the recorder cuts your speech into utterances; each one is transcribed locally and becomes a turn.
              The window closes after `session_idle_s` of quiet, but never while an approval or a turn is outstanding.

Security properties enforced here (and in the broker):
  * Half duplex. The recorder is OFF while FRIDAY speaks and for `echo_guard_ms` afterwards, so FRIDAY never transcribes
    its own voice and a "yes" in a spoken reply can never become an approval.
  * Only approvals raised during a VOICE turn can be answered by voice. A request caused by something typed or by a
    reminder is never read out and never answerable by voice.
  * T2: the exact action is read back first (text built by code from the exact arguments); a "yes" counts only once
    that readback has played to the end uninterrupted, and only if it is a short, clean "yes".
  * T3: the random challenge phrase is shown on screen only. It is never spoken, and the broker accepts only that phrase.
  * "No" / "cancel" / "stop" always denies. The kill switch stops speech, closes the window and drops queued turns.
  * Spoken text is redacted before it reaches a TTS provider, and audio is never stored or logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from ..core.config import VoiceConfig
from ..core.daemon import FridayCore
from ..core.errors import AdmissionError
from ..security.tiers import ConfirmChannel
from ..sensors.activation import ActivationFusion
from ..sensors.audio_hub import SAMPLE_RATE, AudioHub, Frame
from ..sensors.clap import ClapDetector
from ..sensors.speaker import Speaker
from ..sensors.speech_text import is_negative, meaningful, speakable, strip_unspeakable
from ..sensors.stt import Transcriber
from ..sensors.vad import Endpointer, Utterance
from ..sensors.wakeword import STOP, WAKE, WakeWorker, normalize

log = logging.getLogger("friday.voice")


@dataclass
class _VoiceReq:
    tier: int
    readback: str
    complete: bool                 # the readback says everything; otherwise this can only be approved on screen
    created: float = 0.0
    readback_ok: bool = False
    readback_end: float = 0.0      # when the readback finished playing (utterances that began earlier cannot answer it)


@dataclass
class _Heard:
    utt: Utterance
    started: float                 # channel-clock time the speech began


class VoiceChannel:
    def __init__(
        self,
        core: FridayCore,
        cfg: VoiceConfig,
        *,
        hub: AudioHub | None,
        speaker: Speaker,
        stt: Transcriber | None,
        clap: ClapDetector | None,
        endpointer: Endpointer,
        wake: WakeWorker | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.core = core
        self.cfg = cfg
        self.hub = hub
        self.speaker = speaker
        self.stt = stt
        self.clap = clap
        self.endpointer = endpointer
        self.wake = wake
        self._clock = clock
        self._loop: asyncio.AbstractEventLoop | None = None
        self.session_active = False
        self._turn_running = False
        self._last_activity = 0.0
        self._quiet_until = 0.0            # recorder stays off until this time (right after an activation)
        self._recorder_on = False
        self._reqs: dict[str, _VoiceReq] = {}
        self._utt_q: asyncio.Queue[_Heard] = asyncio.Queue(maxsize=4)
        self._turn_q: asyncio.Queue[str] = asyncio.Queue(maxsize=4)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._stopped = True
        self._empty_streak = 0
        self.idle_poll_s = 0.5
        self._reminders: list[str] = []
        self._reminder_task: asyncio.Task[Any] | None = None
        self.fusion = ActivationFusion(
            cfg.activation, self._activation_from_thread,
            debounce_s=cfg.activation_debounce_s, both_window_s=cfg.both_window_s, clock=clock,
        )
        speaker._on_busy = self._on_speaking          # noqa: SLF001 - the channel owns its speaker
        if wake is not None:
            wake._on_event = self._on_wake_event      # noqa: SLF001
            wake._on_failure = self._on_wake_failure  # noqa: SLF001

    # ================================================================== lifecycle
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stopped = False
        bus = self.core.bus
        self._bus_regs = [("confirm.requested", self._on_confirm_requested), ("confirm.resolved", self._on_confirm_resolved),
                          ("kill.tripped", self._on_kill), ("reminder.due", self._on_reminder)]
        for pattern, cb in self._bus_regs:
            bus.on(pattern, cb)
        self.core.context.add_live_source("Input mode", self._input_mode_line)
        if self.hub is not None and self.stt is not None:
            if self.wake:
                self.wake.start()
            self._spawn(self._forever("utterance loop", self._utterance_step))
            self._spawn(self._forever("turn worker", self._turn_step))
            self._spawn(self._forever("idle watch", self._idle_step))
            self.hub.subscribe("voice", self._on_frame)
            self.hub.start()
        self.core.audit.append(
            "voice", "voice.started",
            {"activation": self.cfg.activation, "wake": self.wake is not None, "listening": self.hub is not None and self.stt is not None},
        )

    async def stop(self) -> None:
        self._stopped = True
        for pattern, cb in getattr(self, "_bus_regs", []):
            self.core.bus.off(pattern, cb)
        self._bus_regs = []
        self.core.context.remove_live_source(self._input_mode_line)
        if self.hub is not None:
            self.hub.unsubscribe("voice")
            self.hub.stop()
        if self.wake:
            self.wake.stop()
        self.speaker.interrupt()
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self.session_active = False
        self.core.audit.append("voice", "voice.stopped", {})

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _forever(self, name: str, step: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Run one iteration of a background loop forever. An unexpected error is logged and the loop carries on, so one
        bad utterance or one odd state can never leave the channel deaf."""
        while True:
            try:
                await step()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.error("voice %s hit an error and continues: %s: %s", name, type(exc).__name__, exc)
                await asyncio.sleep(0.2)

    def _input_mode_line(self) -> str | None:
        if not self.session_active:
            return None
        return "voice (your reply will be spoken aloud: answer in full, in a natural conversational way and finish your thoughts; keep it clear and to the point, plain text, no markdown, lists or links. You will not be interrupted while you speak)"

    # ================================================================== audio thread side
    def _on_frame(self, frame: Frame) -> None:
        """Runs on the audio hub thread for every 20 ms frame. Must stay fast."""
        # While FRIDAY talks (and for the echo guard after), her own voice is in the microphone. Unless barge-in is allowed,
        # the clap detector and the wake/stop engine are not even fed, so she can never cut herself off.
        speaking = self._speech_gate()
        if self.clap is not None and (not speaking or self.cfg.barge_in == "any") and self.clap.feed(frame.level, frame.t):
            self.fusion.trigger("clap")
        if self.wake is not None and (not speaking or self.cfg.barge_in != "off"):
            self.wake.offer(frame)
        self._record(frame)

    def _record(self, frame: Frame) -> None:
        gated = (
            not self.session_active
            or self.speaker.busy
            or self._clock() < self.speaker.last_end + self.cfg.echo_guard_ms / 1000.0
            or self._clock() < self._quiet_until
            or self.core.kill.tripped
        )
        if gated:
            if self._recorder_on:
                self.endpointer.reset()
                self._recorder_on = False
            return
        self._recorder_on = True
        utt = self.endpointer.feed(frame)
        if utt is not None and self._loop is not None:
            now = self._clock()
            started = now - len(utt.pcm) / 2 / SAMPLE_RATE - self.cfg.vad_silence_ms / 1000.0
            self._loop.call_soon_threadsafe(self._enqueue_utterance, utt, started)

    def _on_wake_event(self, event: str, t: float) -> None:
        if event == WAKE:
            self.fusion.trigger("wake")
        elif event == STOP and self.speaker.busy and self.cfg.barge_in != "off":
            self.speaker.interrupt()

    def _on_wake_failure(self, why: str) -> None:
        if self._loop is not None and not self._stopped:
            self._loop.call_soon_threadsafe(
                self.core.bus.publish, "core.warning", {"message": f"the wake-phrase engine stopped ({why}); clap activation still works"}
            )

    def _speech_gate(self) -> bool:
        """True while FRIDAY is speaking or its own voice may still be in the air."""
        return self.speaker.busy or self._clock() < self.speaker.last_end + self.cfg.echo_guard_ms / 1000.0

    def _activation_from_thread(self, sources: tuple[str, ...]) -> None:
        if self._loop is not None and not self._stopped:
            self._loop.call_soon_threadsafe(self._on_activate, sources)

    def _enqueue_utterance(self, utt: Utterance, started: float | None = None) -> None:
        if self._utt_q.full():          # the transcriber is behind: drop the oldest rather than grow
            with contextlib.suppress(asyncio.QueueEmpty):
                self._utt_q.get_nowait()
        self._utt_q.put_nowait(_Heard(utt, self._clock() if started is None else started))

    # ================================================================== activation
    def _on_activate(self, sources: tuple[str, ...]) -> None:
        if self._stopped:
            return
        if self.core.kill.tripped:
            self.core.audit.append("voice", "voice.activation_refused", {"sources": list(sources), "why": "kill switch engaged"})
            return
        if self._speech_gate():
            # FRIDAY's own voice (or an echo of it) must never open a session. With a session already open, a clap or the
            # wake phrase is a barge-in: it only stops the speech.
            if self.session_active and self.cfg.barge_in == "any":
                self.speaker.interrupt()
            elif not self.session_active:
                self.core.audit.append("voice", "voice.activation_refused", {"sources": list(sources), "why": "FRIDAY was speaking"})
            return
        self.core.audit.append("voice", "voice.activated", {"sources": list(sources), "was_active": self.session_active})
        self._touch()
        # the tail of the wake phrase / the clap itself must not be recorded as a command
        self._quiet_until = self._clock() + 0.6
        self.endpointer.reset()
        if self.session_active:
            self.speaker.interrupt()          # re-activation while speaking is a barge-in
            self._publish_state("listening")
            return
        self.session_active = True
        self._publish_state("listening")
        greeting = self.cfg.greeting.replace("{name}", self.core.cfg.conversation.user_name)
        self._spawn(self._say(greeting, cacheable=True))

    def _touch(self) -> None:
        self._last_activity = self._clock()

    def _close_session(self, why: str) -> None:
        if not self.session_active:
            return
        self.session_active = False
        self.endpointer.reset()
        self._recorder_on = False
        self.core.audit.append("voice", "voice.session_closed", {"why": why})
        self._publish_state("idle")

    async def _idle_step(self) -> None:
        await asyncio.sleep(self.idle_poll_s)
        if self._reqs:
            self.core.broker.pending()           # sweeps expired approvals, so "that request timed out" is spoken promptly
        if not self.session_active:
            return
        if self.speaker.busy or self._turn_running or self._reqs or not self._turn_q.empty() or not self._utt_q.empty() or self.endpointer.in_speech:
            self._touch()
            return
        idle_since = max(self._last_activity, self.speaker.last_end)
        if self._clock() - idle_since > self.cfg.session_idle_s:
            self._close_session("idle")

    def _publish_state(self, state: str) -> None:
        self.core.bus.publish("voice.state", {"state": state})

    def _on_speaking(self, busy: bool) -> None:
        self._publish_state("speaking" if busy else ("listening" if self.session_active else "idle"))

    # ================================================================== speaking
    def _prepare(self, text: str, limit: int | None = None) -> str:
        """Redact secrets and make the text sayable. Everything spoken passes through here before any TTS provider sees it."""
        return speakable(self.core.redactor.text(text), limit or self.cfg.max_spoken_chars)

    async def _say(self, text: str, *, cacheable: bool = False) -> str:
        res = await self.speaker.say(self._prepare(text), cacheable=cacheable)
        return res.status

    async def _say_exact(self, text: str) -> str:
        """Speak `text` word for word: redacted and stripped of control characters, but never summarised, shortened or
        rewritten (no URL -> "a link"). Used for the approval readback, which must be exactly what will happen."""
        res = await self.speaker.say(strip_unspeakable(self.core.redactor.text(text)))
        return res.status

    # ================================================================== hearing
    async def _utterance_step(self) -> None:
        heard = await self._utt_q.get()
        if not self.session_active or self._stopped:
            return
        try:
            text = await asyncio.to_thread(self._transcribe, heard.utt.pcm)
        except Exception as exc:  # noqa: BLE001 - a broken model must not kill the channel
            log.warning("transcription failed: %s: %s", type(exc).__name__, exc)
            self._empty_streak += 1
            if self._empty_streak in (1, 5):
                self.core.bus.publish("core.warning", {"message": f"speech recognition failed: {exc}"})
            return
        text = self._strip_wake_phrase(strip_unspeakable(text))
        if not meaningful(text):
            self._empty_streak += 1
            return
        self._empty_streak = 0
        self._touch()
        self.core.bus.publish("voice.heard", {"text": text})
        if self._route_confirmation(text, heard.started):
            return
        try:
            self._turn_q.put_nowait(text)
        except asyncio.QueueFull:
            self._spawn(self._say("One moment."))

    def _transcribe(self, pcm: bytes) -> str:
        assert self.stt is not None          # the utterance loop only runs when speech recognition exists
        return self.stt.transcribe(pcm)

    def _strip_wake_phrase(self, text: str) -> str:
        """The recorder can catch the end of "FRIDAY wake up" itself; that is not a command."""
        w = normalize(text)
        for phrase in self.cfg.wake_phrases:
            p = normalize(phrase)
            if p and w[: len(p)] == p:
                return " ".join(w[len(p):])
        return text

    # ================================================================== turns
    async def _turn_step(self) -> None:
        text = await self._turn_q.get()
        if self.core.kill.tripped or not self.session_active:
            return
        self._turn_running = True
        self._publish_state("thinking")
        try:
            result = await self.core.submit(text, "voice", voice_session_active=self.session_active)
            reply, status = result.text, result.status
        except AdmissionError as exc:
            log.warning("voice input refused: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("voice turn failed: %s: %s", type(exc).__name__, exc)
            reply, status = "Something went wrong with that.", "error"
        finally:
            self._turn_running = False
        self._touch()
        if self.core.kill.tripped:
            return
        if status == "ok" and not reply.strip():
            reply = "Done."
        await self._say(reply)
        self._touch()

    # ================================================================== voice confirmations
    def _on_confirm_requested(self, ev: Any) -> None:
        p = ev.payload
        # Only an approval raised by a turn that came in BY VOICE belongs to the voice channel. Something typed, scheduled or
        # sent from elsewhere is never read out and can never be answered by voice, even while a voice session is open.
        if self._stopped or not self.session_active or p.get("origin") != "voice":
            return
        self._reqs[p["id"]] = _VoiceReq(
            tier=int(p["tier"]), readback=str(p.get("readback", "")), complete=bool(p.get("readback_complete", False)), created=self._clock()
        )
        self._spawn(self._announce(p["id"]))

    def _on_confirm_resolved(self, ev: Any) -> None:
        rid = ev.payload.get("id")
        st = self._reqs.pop(rid, None)
        if st is not None and ev.payload.get("state") == "expired" and self.session_active and not self.core.kill.tripped:
            self._spawn(self._say("That request timed out."))

    async def _announce(self, rid: str) -> None:
        st = self._reqs.get(rid)
        if st is None:
            return
        if st.tier >= 3:
            # the challenge phrase is shown on screen only and is never spoken
            tail = " This needs the challenge phrase shown on your screen. Say it to approve, or say no to cancel."
            await self._say_exact(st.readback + tail)
            return
        if not st.complete:
            await self._say("That one is too detailed to read out. Please check it on your screen and approve it there, or say no to cancel.")
            return
        status = await self._say_exact(st.readback + " Say yes to approve, or no to cancel.")
        st.readback_ok = status == "done"
        if st.readback_ok:
            st.readback_end = self._clock()

    def _route_confirmation(self, text: str, started: float | None = None) -> bool:
        """If a voice-owned approval is waiting, this utterance is the answer to it (never a new command)."""
        pending = [r for r in self.core.broker.pending() if r.id in self._reqs]
        if not pending:
            return False
        req = pending[0]
        st = self._reqs[req.id]
        if is_negative(text):
            self.core.respond_confirmation(req.id, False, ConfirmChannel.VOICE, text=text, voice_session_active=self.session_active)
            self._spawn(self._say("Cancelled."))
            return True
        if req.tier < 3 and not st.complete:
            self._spawn(self._say("Please approve that one on your screen, or say no to cancel."))
            return True
        if req.tier < 3 and not st.readback_ok:
            # A "yes" before the readback finished is not an approval: say it again, in full.
            self._spawn(self._say("Let me read that again."))
            self._spawn(self._announce(req.id))
            return True
        valid_from = st.readback_end if req.tier < 3 else st.created
        if started is not None and started < valid_from:
            # speech that began before the readback ended (or before the request existed) was not an answer to it
            self.core.audit.append("voice", "voice.stale_answer_ignored", {"id": req.id})
            return True
        res = self.core.respond_confirmation(
            req.id, True, ConfirmChannel.VOICE, text=text, readback_confirmed=st.readback_ok, voice_session_active=self.session_active
        )
        self._spawn(self._say("Approved." if res.ok else res.reason))
        return True

    # ================================================================== kill switch, reminders
    def _on_kill(self, ev: Any) -> None:
        """May run on any thread (a hotkey, a UI button): stop the speech now, do the queue work on the loop."""
        self.speaker.interrupt()
        if self._loop is not None and not self._stopped:
            self._loop.call_soon_threadsafe(self._after_kill)

    def _after_kill(self) -> None:
        while not self._turn_q.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._turn_q.get_nowait()
        self._reqs.clear()
        self._close_session("kill switch")

    def _on_reminder(self, ev: Any) -> None:
        if self._stopped or not self.cfg.speak_reminders or self.core.kill.tripped:
            return
        p = ev.payload
        lead = "Missed reminder: " if p.get("late") else "Reminder: "
        if len(self._reminders) < 20:
            self._reminders.append(lead + str(p.get("message", "")))
        if self._reminder_task is None or self._reminder_task.done():
            self._reminder_task = self._spawn(self._say_reminders())

    async def _say_reminders(self) -> None:
        """Several reminders that fire together are spoken as one short announcement, not a queue of long ones. Reminders that
        arrive while one is being spoken are picked up by the same loop (none is ever left behind)."""
        while self._reminders and not self._stopped:
            await asyncio.sleep(0.05)
            pending, self._reminders = self._reminders, []
            if not pending:
                return
            text = " ".join(pending[:3])
            if len(pending) > 3:
                text += f" And {len(pending) - 3} more on screen."
            await self._say(text)
