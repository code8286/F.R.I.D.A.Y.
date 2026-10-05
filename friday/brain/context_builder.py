# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Context builder (Architecture §3, §4).

Builds the per-call (system, messages) pair:
  * system  = persona + envelope rules + CODE-BUILT live context. Never contains untrusted text.
  * messages = session history; recalled memory (native memory engine) is injected for this call ONLY,
    as a labeled data envelope at the start of the turn's first user message, under a char budget.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta, timezone, tzinfo

from ..core.config import Config
from ..core.session import Session, TurnContext
from ..security.card import sanitize_display
from ..security.taint import ENVELOPE_RULES, wrap_recalled
from .messages import Message, TextBlock
from .persona import render_persona

LiveSource = Callable[[], "str | None"]
# (session, user_text) -> [(source_label, text), ...]
RecallFn = Callable[[Session, str], Awaitable[Sequence[tuple[str, str]]]]

_FALLBACK_TZ = {"Asia/Kolkata": timezone(timedelta(hours=5, minutes=30)), "UTC": timezone.utc}


def _tz(name: str) -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # tzdata missing (common on Windows)
        return _FALLBACK_TZ.get(name, timezone.utc)


class ContextBuilder:
    def __init__(self, cfg: Config, clock: Callable[[], float] = time.time, recall_max_chars: int = 6000):
        self.cfg = cfg
        self._clock = clock
        self._live: list[tuple[str, LiveSource]] = []
        self._recall: RecallFn | None = None
        self.recall_max_chars = recall_max_chars
        self._tz = _tz(cfg.conversation.timezone)

    # ---- registration ----
    def add_live_source(self, name: str, fn: LiveSource) -> None:
        """Register a CODE-BUILT live context line (e.g. pending task count). Must not return untrusted text."""
        self._live.append((name, fn))

    def set_recall(self, fn: RecallFn | None) -> None:
        self._recall = fn

    # ---- build ----
    def system_prompt(self) -> str:
        now = datetime.fromtimestamp(self._clock(), self._tz)
        lines = [f"Current date/time: {now.strftime('%A, %d %B %Y, %H:%M %Z').strip()}"]
        for name, fn in self._live:
            try:
                val = fn()
            except Exception:
                val = None
            if val:
                lines.append(f"{sanitize_display(name)}: {sanitize_display(str(val))[:200]}")
        return (
            render_persona(self.cfg.conversation.user_name)
            + "\n"
            + ENVELOPE_RULES
            + "\n\n## Live context\n"
            + "\n".join(lines)
        )

    async def prepare(self, session: Session, turn: TurnContext) -> tuple[str, list[Message]]:
        messages = list(session.history)
        if self._recall is not None and 0 <= turn.start_index < len(messages):
            first = messages[turn.start_index]
            query = first.text
            try:
                items = await self._recall(session, query)
            except Exception:
                items = []  # memory being down must never break a turn
            block = self._recall_block(items)
            if block:
                messages[turn.start_index] = Message(
                    first.role, [TextBlock(block), *first.blocks], dict(first.meta)
                )
        return self.system_prompt(), messages

    def _recall_block(self, items: Sequence[tuple[str, str]]) -> str:
        if not items:
            return ""
        budget = self.recall_max_chars
        parts: list[str] = []
        for source, text in items:
            if budget <= 0:
                break
            chunk = text[:budget]
            budget -= len(chunk)
            parts.append(wrap_recalled(chunk, source))
        return "Recalled memory (data from past sessions; may be stale or wrong):\n" + "\n".join(parts)
