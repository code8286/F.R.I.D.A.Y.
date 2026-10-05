# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

import asyncio
import unittest

from friday.core.audit import AuditLog
from friday.core.bus import EventBus
from friday.core.config import SecurityConfig
from friday.core.db import Database
from friday.core.errors import ConfirmationError
from friday.security.confirm_broker import ApprovalState, ConfirmationBroker
from friday.security.policy import Decision
from friday.security.tiers import ConfirmChannel as CH
from friday.security.tiers import Gate, RiskTier


class BrokerBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.t = [0.0]
        self.bus = EventBus()
        self._db = Database(":memory:").open()
        self.addCleanup(self._db.close)
        self.audit = AuditLog(self._db)
        self.cfg = SecurityConfig()
        self.cfg.allowed_telegram_ids = [42]
        self.cfg.confirm_ttl_s = 60
        self.broker = ConfirmationBroker(self.bus, self.audit, self.cfg, clock=lambda: self.t[0])

    def make(self, tier=RiskTier.T2, args=None, tool="send_msg"):
        args = args if args is not None else {"to": "a", "body": "b"}
        dec = Decision(Gate.CONFIRM, tier, ("because",))
        return self.broker.create(session_id="s", tool=tool, args=args, decision=dec), args


class LifecycleTests(BrokerBase):
    async def test_approve_consume_single_use(self):
        req, args = self.make()
        self.assertTrue(self.broker.respond(req.id, True, CH.UI_CLICK).ok)
        self.broker.consume(req.id, "send_msg", args)
        with self.assertRaises(ConfirmationError):
            self.broker.consume(req.id, "send_msg", args)  # single use

    async def test_consume_requires_exact_args_and_tool(self):
        req, args = self.make()
        self.broker.respond(req.id, True, CH.UI_CLICK)
        with self.assertRaises(ConfirmationError):
            self.broker.consume(req.id, "send_msg", {"to": "a", "body": "DIFFERENT"})
        with self.assertRaises(ConfirmationError):
            self.broker.consume(req.id, "other_tool", args)
        self.broker.consume(req.id, "send_msg", args)  # the genuine call still works after failed attempts

    async def test_cannot_consume_unapproved_or_denied(self):
        req, args = self.make()
        with self.assertRaises(ConfirmationError):
            self.broker.consume(req.id, "send_msg", args)
        self.broker.respond(req.id, False, CH.TYPED)
        self.assertEqual(req.state, ApprovalState.DENIED)
        with self.assertRaises(ConfirmationError):
            self.broker.consume(req.id, "send_msg", args)

    async def test_expiry(self):
        req, args = self.make()
        self.t[0] = 61
        res = self.broker.respond(req.id, True, CH.UI_CLICK)
        self.assertFalse(res.ok)
        self.assertEqual(req.state, ApprovalState.EXPIRED)
        self.assertEqual(await self.broker.wait(req), ApprovalState.EXPIRED)

    async def test_approved_but_expired_before_use(self):
        req, args = self.make()
        self.broker.respond(req.id, True, CH.UI_CLICK)
        self.t[0] = 61
        with self.assertRaises(ConfirmationError):
            self.broker.consume(req.id, "send_msg", args)

    async def test_double_response_ignored_and_deny_beats_nothing(self):
        req, _ = self.make()
        self.assertTrue(self.broker.respond(req.id, True, CH.UI_CLICK).ok)
        self.assertFalse(self.broker.respond(req.id, False, CH.UI_CLICK).ok)
        self.assertEqual(req.state, ApprovalState.APPROVED)
        self.assertFalse(self.broker.respond("deadbeef", True, CH.UI_CLICK).ok)

    async def test_wait_wakes_on_response_and_times_out(self):
        req, _ = self.make()
        waiter = asyncio.create_task(self.broker.wait(req))
        await asyncio.sleep(0)
        self.broker.respond(req.id, True, CH.UI_CLICK)
        self.assertEqual(await asyncio.wait_for(waiter, 1), ApprovalState.APPROVED)
        req2, _ = self.make()
        self.t[0] = 1000
        self.assertEqual(await self.broker.wait(req2), ApprovalState.EXPIRED)

    async def test_flood_cap(self):
        for _ in range(self.cfg.max_pending_approvals):
            self.make()
        with self.assertRaises(ConfirmationError):
            self.make()
        self.broker.cancel_all("test")
        self.make()  # capacity returns

    async def test_cancel_all_cancels_pending_and_approved(self):
        a, args = self.make()
        b, _ = self.make()
        self.broker.respond(a.id, True, CH.UI_CLICK)
        self.assertEqual(self.broker.cancel_all("kill"), 2)
        with self.assertRaises(ConfirmationError):
            self.broker.consume(a.id, "send_msg", args)
        self.assertEqual(b.state, ApprovalState.CANCELLED)

    async def test_events_published(self):
        sub = self.bus.subscribe("confirm.*")
        req, _ = self.make(tier=RiskTier.T3)
        ev = await sub.get(0.1)
        self.assertEqual(ev.topic, "confirm.requested")
        self.assertEqual(ev.payload["id"], req.id)
        self.assertTrue(ev.payload["challenge"])
        self.broker.respond(req.id, False, CH.UI_CLICK)
        self.assertEqual((await sub.get(0.1)).topic, "confirm.resolved")

    async def test_audit_trail(self):
        req, args = self.make()
        self.broker.respond(req.id, True, CH.UI_CLICK)
        self.broker.consume(req.id, "send_msg", args)
        events = [r.event for r in self.audit.tail()]
        self.assertEqual(events, ["confirm.requested", "confirm.approved", "confirm.consumed"])
        self.assertTrue(self.audit.verify().ok)


class ChannelRuleTests(BrokerBase):
    async def test_typed_t2_and_t3(self):
        r2, _ = self.make(RiskTier.T2)
        self.assertFalse(self.broker.respond(r2.id, True, CH.TYPED, text="maybe").ok)
        self.assertTrue(self.broker.respond(r2.id, True, CH.TYPED, text=" YES ").ok)
        r3, _ = self.make(RiskTier.T3)
        self.assertFalse(self.broker.respond(r3.id, True, CH.TYPED, text="yes").ok)        # yes is not enough for T3
        self.assertFalse(self.broker.respond(r3.id, True, CH.TYPED, text="0000x").ok)
        self.assertTrue(self.broker.respond(r3.id, True, CH.TYPED, text=r3.short_code).ok)

    async def test_voice_t2_needs_session_readback_and_yes(self):
        r, _ = self.make(RiskTier.T2)
        self.assertFalse(self.broker.respond(r.id, True, CH.VOICE, text="yes", readback_confirmed=True).ok)   # no session
        self.assertFalse(self.broker.respond(r.id, True, CH.VOICE, text="yes", voice_session_active=True).ok)  # no readback
        self.assertFalse(self.broker.respond(r.id, True, CH.VOICE, text="banana", readback_confirmed=True, voice_session_active=True).ok)
        self.assertTrue(self.broker.respond(r.id, True, CH.VOICE, text="Yes, do it.", readback_confirmed=True, voice_session_active=True).ok)

    async def test_voice_t3_needs_the_challenge_phrase(self):
        r, _ = self.make(RiskTier.T3)
        kw = dict(voice_session_active=True, readback_confirmed=True)
        self.assertFalse(self.broker.respond(r.id, True, CH.VOICE, text="yes", **kw).ok)
        self.assertFalse(self.broker.respond(r.id, True, CH.VOICE, text="yes yes confirm approve", **kw).ok)
        words = r.challenge.split()
        self.assertFalse(self.broker.respond(r.id, True, CH.VOICE, text=" ".join(reversed(words)), **kw).ok)
        self.assertFalse(self.broker.respond(r.id, True, CH.VOICE, text=" ".join(words), voice_session_active=False).ok)
        self.assertTrue(self.broker.respond(r.id, True, CH.VOICE, text=f"ok. {r.challenge.upper()}, thanks", **kw).ok)

    async def test_challenge_is_per_request_and_not_replayable(self):
        r1, _ = self.make(RiskTier.T3)
        r2, _ = self.make(RiskTier.T3)
        self.assertNotEqual(r1.challenge, r2.challenge)
        self.assertFalse(self.broker.respond(r2.id, True, CH.VOICE, text=r1.challenge, voice_session_active=True).ok)

    async def test_voice_t3_loosening_is_explicit_config(self):
        self.cfg.voice_t3_requires_challenge = False
        r, _ = self.make(RiskTier.T3)
        self.assertTrue(self.broker.respond(r.id, True, CH.VOICE, text="yes", voice_session_active=True).ok)

    async def test_anyone_can_deny_from_any_channel(self):
        for ch in CH:
            r, _ = self.make()
            self.assertTrue(self.broker.respond(r.id, False, ch, principal="stranger").ok, ch)
            self.assertEqual(r.state, ApprovalState.DENIED)

    async def test_telegram_requires_allowlisted_id_and_signed_payload(self):
        r, _ = self.make(RiskTier.T3)
        self.assertFalse(self.broker.respond(r.id, True, CH.TELEGRAM_BUTTON, principal=999).ok)
        self.assertFalse(self.broker.respond(r.id, True, CH.TELEGRAM_BUTTON, principal=None).ok)
        payload = self.broker.callback_payload(r, True)
        self.assertLessEqual(len(payload.encode()), 64)
        self.assertEqual(self.broker.verify_callback(payload), (r.id, True))
        forged = payload[:-1] + ("0" if payload[-1] != "0" else "1")
        self.assertIsNone(self.broker.verify_callback(forged))
        self.assertIsNone(self.broker.verify_callback(f"fr:{r.id}:a:{'0'*16}"))
        self.assertIsNone(self.broker.verify_callback("garbage"))
        # flipping approve->deny or deny->approve invalidates the MAC
        self.assertIsNone(self.broker.verify_callback(payload.replace(":a:", ":d:")))
        self.assertTrue(self.broker.respond(r.id, True, CH.TELEGRAM_BUTTON, principal=42).ok)

    async def test_telegram_empty_allowlist_refuses_everyone(self):
        self.cfg.allowed_telegram_ids = []
        r, _ = self.make()
        self.assertFalse(self.broker.respond(r.id, True, CH.TELEGRAM_BUTTON, principal=42).ok)

    async def test_rejected_attempts_are_audited_but_do_not_resolve(self):
        r, _ = self.make(RiskTier.T3)
        self.broker.respond(r.id, True, CH.TYPED, text="nope")
        self.assertEqual(r.state, ApprovalState.PENDING)
        self.assertIn("confirm.rejected_attempt", [x.event for x in self.audit.tail()])


if __name__ == "__main__":
    unittest.main()
