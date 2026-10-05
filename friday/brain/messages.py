# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Canonical message format used everywhere inside FRIDAY.

Providers translate to/from their own wire format; nothing else in the codebase sees a wire format.
`Message.meta` carries FRIDAY-only metadata (source channel, trust, `tainted`) and is never sent to a
provider.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class TextBlock:
    text: str
    type: str = "text"


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    arguments: dict[str, Any]
    type: str = "tool_use"


@dataclass(frozen=True)
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False
    type: str = "tool_result"


Block = TextBlock | ToolUseBlock | ToolResultBlock
Role = Literal["user", "assistant"]


@dataclass
class Message:
    role: Role
    blocks: list[Block]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks if isinstance(b, TextBlock))

    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.blocks if isinstance(b, ToolUseBlock)]

    def tool_results(self) -> list[ToolResultBlock]:
        return [b for b in self.blocks if isinstance(b, ToolResultBlock)]

    def is_turn_start(self) -> bool:
        """A user message that starts a new turn (carries text, not just tool results)."""
        return self.role == "user" and any(isinstance(b, TextBlock) for b in self.blocks)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


StopReason = Literal["end_turn", "tool_use", "max_tokens", "other"]


@dataclass
class LLMResponse:
    blocks: list[Block]
    stop_reason: StopReason = "end_turn"
    usage: Usage = field(default_factory=Usage)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks if isinstance(b, TextBlock))

    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.blocks if isinstance(b, ToolUseBlock)]


# ---- helpers ---------------------------------------------------------------------------------
def user_text(text: str, **meta: Any) -> Message:
    return Message("user", [TextBlock(text)], dict(meta))


def assistant_text(text: str, **meta: Any) -> Message:
    return Message("assistant", [TextBlock(text)], dict(meta))


def estimate_tokens(msg: Message) -> int:
    """Rough token estimate (chars/4). Good enough for trim budgets."""
    n = 0
    for b in msg.blocks:
        if isinstance(b, TextBlock):
            n += len(b.text)
        elif isinstance(b, ToolUseBlock):
            n += len(b.name) + len(json.dumps(b.arguments, default=str))
        elif isinstance(b, ToolResultBlock):
            n += len(b.content)
    return n // 4 + 4


# ---- (de)serialisation -------------------------------------------------------------------------
def block_to_dict(b: Block) -> dict[str, Any]:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ToolUseBlock):
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.arguments}
    return {"type": "tool_result", "tool_use_id": b.tool_use_id, "content": b.content, "is_error": b.is_error}


def block_from_dict(d: dict[str, Any]) -> Block:
    t = d.get("type")
    if t == "text":
        return TextBlock(str(d.get("text", "")))
    if t == "tool_use":
        args = d.get("input", d.get("arguments", {}))
        return ToolUseBlock(str(d["id"]), str(d["name"]), args if isinstance(args, dict) else {})
    if t == "tool_result":
        return ToolResultBlock(str(d["tool_use_id"]), str(d.get("content", "")), bool(d.get("is_error", False)))
    raise ValueError(f"unknown block type {t!r}")


def message_to_dict(m: Message) -> dict[str, Any]:
    return {"role": m.role, "content": [block_to_dict(b) for b in m.blocks]}


def check_pairing(messages: list[Message]) -> list[str]:
    """Return a list of problems with tool_use/tool_result pairing and role alternation (empty = valid)."""
    problems: list[str] = []
    open_ids: set[str] = set()
    prev_role: str | None = None
    for i, m in enumerate(messages):
        if prev_role == m.role:
            problems.append(f"#{i}: two consecutive {m.role} messages")
        prev_role = m.role
        if m.role == "assistant":
            if open_ids:
                problems.append(f"#{i}: unanswered tool_use ids {sorted(open_ids)}")
            open_ids = {b.id for b in m.tool_uses()}
        else:
            answered = {b.tool_use_id for b in m.tool_results()}
            if answered - open_ids:
                problems.append(f"#{i}: orphan tool_result for {sorted(answered - open_ids)}")
            if open_ids - answered:
                problems.append(f"#{i}: missing tool_result for {sorted(open_ids - answered)}")
            open_ids = set()
    if open_ids:
        problems.append("history ends with unanswered tool_use")
    return problems
