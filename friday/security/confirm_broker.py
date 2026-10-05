# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Confirmation broker (Architecture §6.4).

Lifecycle of an approval:   PENDING -> APPROVED -> CONSUMED
                                   \\-> DENIED | EXPIRED | CANCELLED

Guarantees enforced here, in code:
  * Approvals are bound to sha256(tool, exact arguments); `consume()` refuses any other arguments.
  * Single use, and they expire (default 60 s from creation).
  * Channel rules per tier:
        UI_CLICK         : T2, T3
        TYPED            : T2 -> "yes"/"y"/"approve" or the short code;  T3 -> the short code
        TELEGRAM_BUTTON  : T2, T3 — only from an allow-listed Telegram user id, with an HMAC'd payload
        VOICE            : T2 -> spoken yes AFTER a readback of the card;  T3 -> the random challenge phrase
    A voice "yes" alone can never approve T3 (a spoofed or replayed yes is a real attack). The challenge
    phrase is shown on screen / Telegram and must NEVER be spoken aloud by TTS.
  * Anyone can deny, from any channel.
  * A cap on simultaneously pending approvals stops approval flooding.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.audit import AuditLog
from ..core.bus import EventBus
from ..core.config import SecurityConfig
from ..core.errors import ConfirmationError
from .card import args_hash, render_card
from .policy import Decision
from .tiers import ConfirmChannel, RiskTier

_WORDS = ["amber", "anchor", "apple", "arrow", "aspen", "badger", "basil", "beacon", "birch", "bison", "bolt", "breeze", "bronze", "cedar", "clover", "cobalt", "comet", "copper", "coral", "crane", "crimson", "dawn", "delta", "dune", "eagle", "ember", "falcon", "fern", "flint", "forest", "frost", "garnet", "glacier", "granite", "harbor", "hazel", "heron", "indigo", "iris", "ivory", "jade", "jasper", "juniper", "kestrel", "lagoon", "lantern", "lark", "lotus", "maple", "marble", "meadow", "meteor", "mist", "nectar", "nickel", "oak", "onyx", "orchid", "otter", "pearl", "pine", "plume", "quartz", "raven", "reef", "ridge", "river", "saffron", "sage", "silver", "sparrow", "summit", "thistle", "thunder", "topaz", "tundra", "velvet", "willow"]

_YES = {"yes", "y", "approve", "approved", "confirm"}


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    CONSUMED = "consumed"


@dataclass
class ApprovalRequest:
    id: str
    session_id: str
    tool: str
    tier: RiskTier
    reasons: tuple[str, ...]
    card: str
    args_hash: str
    short_code: str
    challenge: str | None
    created_at: float
    expires_at: float
    state: ApprovalState = ApprovalState.PENDING
    decided_via: str | None = None
    event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def public(self) -> dict[str, Any]:
        """What presenters (UI / Telegram) receive. `challenge` is for ON-SCREEN display only, never TTS."""
        return {
            "id": self.id,
            "tool": self.tool,
            "tier": int(self.tier),
            "reasons": list(self.reasons),
            "card": self.card,
            "short_code": self.short_code,
            "challenge": self.challenge,
            "ttl_s": self.expires_at - self.created_at,
        }


@dataclass(frozen=True)
class RespondResult:
    ok: bool
    state: ApprovalState
    reason: str = ""


def _norm_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class ConfirmationBroker:
    def __init__(
        self,
        bus: EventBus,
        audit: AuditLog,
        cfg: SecurityConfig,
        redact: Callable[[str], str] = lambda s: s,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.bus = bus
        self.audit = audit
        self.cfg = cfg
        self._redact = redact
        self._clock = clock
        self._secret = secrets.token_bytes(32)
        self._reqs: dict[str, ApprovalRequest] = {}

    # ------------------------------------------------------------------ create / wait
    def create(self, *, session_id: str, tool: str, args: dict[str, Any], decision: Decision) -> ApprovalRequest:
        self._expire_due()
        pending = [r for r in self._reqs.values() if r.state is ApprovalState.PENDING]
        if len(pending) >= self.cfg.max_pending_approvals:
            self.audit.append("broker", "confirm.flood_refused", {"tool": tool, "pending": len(pending)})
            raise ConfirmationError("too many approvals are already waiting; resolve or deny them first")

        now = self._clock()
        challenge = None
        if decision.tier >= RiskTier.T3:
            challenge = " ".join(secrets.choice(_WORDS) for _ in range(3))
        req = ApprovalRequest(
            id=secrets.token_hex(4),
            session_id=session_id,
            tool=tool,
            tier=decision.tier,
            reasons=decision.reasons,
            card=render_card(tool, args, decision, self._redact),
            args_hash=args_hash(tool, args),
            short_code=f"{secrets.randbelow(10000):04d}",
            challenge=challenge,
            created_at=now,
            expires_at=now + self.cfg.confirm_ttl_s,
        )
        self._reqs[req.id] = req
        self.audit.append(
            "broker", "confirm.requested",
            {"id": req.id, "tool": tool, "tier": int(req.tier), "args_hash": req.args_hash, "reasons": list(req.reasons)},
        )
        self.bus.publish("confirm.requested", req.public())
        return req

    async def wait(self, req: ApprovalRequest) -> ApprovalState:
        """Wait for a decision or expiry. Returns the final state (never raises on timeout)."""
        remaining = req.expires_at - self._clock()
        if req.state is ApprovalState.PENDING and remaining > 0:
            try:
                await asyncio.wait_for(req.event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass
        self._expire_due()
        return req.state

    # ------------------------------------------------------------------ respond
    def respond(
        self,
        request_id: str,
        approve: bool,
        channel: ConfirmChannel,
        *,
        principal: int | str | None = None,
        text: str | None = None,
        readback_confirmed: bool = False,
        voice_session_active: bool = False,
    ) -> RespondResult:
        self._expire_due()
        req = self._reqs.get(request_id)
        if req is None:
            return RespondResult(False, ApprovalState.EXPIRED, "unknown or expired request")
        if req.state is not ApprovalState.PENDING:
            return RespondResult(False, req.state, f"request is already {req.state.value}")

        if not approve:  # anyone, any channel, can say no
            return self._finish(req, ApprovalState.DENIED, channel, "denied")

        ok, why = self._channel_allows(req, channel, principal, text, readback_confirmed, voice_session_active)
        if not ok:
            self.audit.append("broker", "confirm.rejected_attempt", {"id": req.id, "channel": channel.value, "why": why})
            return RespondResult(False, req.state, why)
        return self._finish(req, ApprovalState.APPROVED, channel, "approved")

    def _channel_allows(
        self,
        req: ApprovalRequest,
        channel: ConfirmChannel,
        principal: int | str | None,
        text: str | None,
        readback_confirmed: bool,
        voice_session_active: bool,
    ) -> tuple[bool, str]:
        t3 = req.tier >= RiskTier.T3

        if channel is ConfirmChannel.UI_CLICK:
            return True, ""

        if channel is ConfirmChannel.TYPED:
            typed = (text or "").strip().lower()
            if t3:
                return (typed == req.short_code, f"type the code {req.short_code} to approve a T3 action")
            return (typed in _YES or typed == req.short_code, "type 'yes' (or the code) to approve")

        if channel is ConfirmChannel.TELEGRAM_BUTTON:
            allowed = self.cfg.allowed_telegram_ids
            if not allowed or principal not in allowed:
                return False, "telegram user is not authorised"
            return True, ""

        if channel is ConfirmChannel.VOICE:
            if not voice_session_active:
                return False, "no active voice session"
            if t3:
                if not self.cfg.voice_t3_requires_challenge:
                    return True, ""
                spoken = _norm_words(text or "")
                want = _norm_words(req.challenge or "")
                if want and _contains_sequence(spoken, want):
                    return True, ""
                return False, "say the challenge phrase shown on screen to approve a T3 action"
            if self.cfg.voice_t2_requires_readback and not readback_confirmed:
                return False, "voice approval needs a readback of the action first"
            spoken = set(_norm_words(text or ""))
            if spoken & _YES:
                return True, ""
            return False, "say 'yes' to approve"

        return False, "unsupported channel"

    def _finish(self, req: ApprovalRequest, state: ApprovalState, channel: ConfirmChannel, verb: str) -> RespondResult:
        req.state = state
        req.decided_via = channel.value
        req.event.set()
        self.audit.append("broker", f"confirm.{verb}", {"id": req.id, "tool": req.tool, "channel": channel.value})
        self.bus.publish("confirm.resolved", {"id": req.id, "state": state.value, "channel": channel.value})
        return RespondResult(True, state, verb)

    # ------------------------------------------------------------------ consume
    def consume(self, request_id: str, tool: str, args: dict[str, Any]) -> None:
        """Called by the loop immediately before executing. Raises ConfirmationError on any mismatch."""
        self._expire_due()
        req = self._reqs.get(request_id)
        if req is None:
            raise ConfirmationError("no such approval")
        if req.state is not ApprovalState.APPROVED:
            raise ConfirmationError(f"approval is {req.state.value}, not approved")
        if self._clock() > req.expires_at:
            req.state = ApprovalState.EXPIRED
            raise ConfirmationError("approval expired before execution")
        if req.tool != tool or not hmac.compare_digest(req.args_hash, args_hash(tool, args)):
            self.audit.append("broker", "confirm.hash_mismatch", {"id": req.id, "tool": tool})
            raise ConfirmationError("approval does not match these exact arguments")
        req.state = ApprovalState.CONSUMED
        self.audit.append("broker", "confirm.consumed", {"id": req.id, "tool": tool})

    # ------------------------------------------------------------------ housekeeping
    def _expire_due(self) -> None:
        now = self._clock()
        for req in self._reqs.values():
            if req.state is ApprovalState.PENDING and now > req.expires_at:
                req.state = ApprovalState.EXPIRED
                req.event.set()
                self.audit.append("broker", "confirm.expired", {"id": req.id, "tool": req.tool})
                self.bus.publish("confirm.resolved", {"id": req.id, "state": "expired", "channel": None})
        # forget finished requests after a while to bound memory
        stale = [
            rid for rid, r in self._reqs.items()
            if r.state is not ApprovalState.PENDING and now > r.expires_at + 300
        ]
        for rid in stale:
            del self._reqs[rid]

    def cancel_all(self, reason: str = "cancelled") -> int:
        n = 0
        for req in self._reqs.values():
            if req.state in (ApprovalState.PENDING, ApprovalState.APPROVED):
                req.state = ApprovalState.CANCELLED
                req.event.set()
                n += 1
                self.audit.append("broker", "confirm.cancelled", {"id": req.id, "reason": reason})
        return n

    def pending(self) -> list[ApprovalRequest]:
        self._expire_due()
        return [r for r in self._reqs.values() if r.state is ApprovalState.PENDING]

    def get(self, request_id: str) -> ApprovalRequest | None:
        return self._reqs.get(request_id)

    # ------------------------------------------------------------------ telegram callbacks
    def callback_payload(self, req: ApprovalRequest, approve: bool) -> str:
        """`callback_data` for a Telegram inline button (<= 64 bytes). HMAC'd so it cannot be forged."""
        a = "a" if approve else "d"
        mac = hmac.new(self._secret, f"{req.id}:{a}".encode(), hashlib.sha256).hexdigest()[:16]
        return f"fr:{req.id}:{a}:{mac}"

    def verify_callback(self, payload: str) -> tuple[str, bool] | None:
        m = re.fullmatch(r"fr:([0-9a-f]{8}):([ad]):([0-9a-f]{16})", payload or "")
        if not m:
            return None
        rid, a, mac = m.groups()
        want = hmac.new(self._secret, f"{rid}:{a}".encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(mac, want):
            return None
        return rid, a == "a"


def _contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))
