# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Sessions, input admission and per-turn state.

FRIDAY keeps ONE logical session thread shared by desktop, voice and Telegram (Architecture §4.4);
each message is tagged with its source channel. Only trusted origins are admitted: your typed input,
your voice during an active voice session, and your allow-listed Telegram ID.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..brain.messages import Message, estimate_tokens
from .audit import AuditLog
from .config import SecurityConfig
from .errors import AdmissionError


@dataclass(frozen=True)
class Origin:
    channel: str                       # "console" | "ui" | "voice" | "telegram"
    principal: int | str | None = None
    trusted: bool = True


class Session:
    def __init__(self, session_id: str = "main"):
        self.id = session_id
        self.created = time.time()
        self.history: list[Message] = []
        self.lock = asyncio.Lock()      # one agent turn at a time per session

    def append(self, msg: Message) -> None:
        self.history.append(msg)

    def is_tainted(self) -> bool:
        """True while any untrusted tool output is still inside the history window."""
        return any(m.meta.get("tainted") for m in self.history)

    def turn_starts(self) -> list[int]:
        return [i for i, m in enumerate(self.history) if m.is_turn_start()]

    def token_estimate(self) -> int:
        return sum(estimate_tokens(m) for m in self.history)

    def trim(self, max_tokens: int, keep_min_turns: int = 2) -> list[Message]:
        """Drop the oldest WHOLE turns until under budget. Never splits a tool_use / tool_result pair.

        Returns the dropped messages (so the memory engine can fold them into the rolling summary).
        """
        dropped: list[Message] = []
        starts = self.turn_starts()
        if starts and starts[0] != 0:  # leading orphan messages: drop them
            dropped += self.history[: starts[0]]
            del self.history[: starts[0]]
            starts = [s - starts[0] for s in starts]
        total = self.token_estimate()
        while total > max_tokens and len(starts) > max(1, keep_min_turns):
            cut = starts[1]
            chunk = self.history[:cut]
            total -= sum(estimate_tokens(m) for m in chunk)
            dropped += chunk
            del self.history[:cut]
            starts = [s - cut for s in starts[1:]]
        return dropped


@dataclass
class TurnContext:
    turn_id: str
    session: Session
    source: str
    start_index: int = 0
    started: float = field(default_factory=time.monotonic)
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new(session: Session, source: str) -> TurnContext:
        return TurnContext(uuid.uuid4().hex[:12], session, source)


class SessionManager:
    def __init__(self, cfg: SecurityConfig, audit: AuditLog | None = None):
        self.cfg = cfg
        self.audit = audit
        self._sessions: dict[str, Session] = {}

    def main(self) -> Session:
        return self._sessions.setdefault("main", Session("main"))

    def admit(self, channel: str, principal: int | str | None = None, *, voice_session_active: bool = False) -> Origin:
        ok, why = self._check(channel, principal, voice_session_active)
        if not ok:
            if self.audit:
                self.audit.append("admission", "input.refused", {"channel": channel, "principal": str(principal), "why": why})
            raise AdmissionError(why)
        return Origin(channel, principal, True)

    def _check(self, channel: str, principal: int | str | None, voice_active: bool) -> tuple[bool, str]:
        if channel in ("console", "ui"):
            return True, ""            # local, already authenticated (terminal / WebSocket token)
        if channel == "voice":
            return (voice_active, "voice input outside an active session")
        if channel == "telegram":
            ids = self.cfg.allowed_telegram_ids
            if not ids:
                return False, "no Telegram user ids are allow-listed"
            return (principal in ids, "telegram user is not allow-listed")
        return False, f"unknown channel {channel!r}"
