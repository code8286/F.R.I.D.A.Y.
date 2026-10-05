# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Strict JSON tool-call protocol — the fallback when an endpoint has no native tool use.

The model must answer with EXACTLY ONE of:

    {"tool_calls": [{"name": "<tool>", "arguments": {...}}, ...]}
    {"final": "<text for the user>"}      (or plain prose, which is treated as a final answer)

A reply is only treated as tool calls if the ENTIRE reply (optionally inside a ```json fence) is that
JSON object. A JSON snippet quoted inside prose — e.g. copied out of an untrusted web page — is never
executed. Calls naming unknown tools or failing schema validation raise ProviderProtocolError.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from ..core.errors import ProviderProtocolError
from ..core.schema import validate
from .messages import Block, Message, TextBlock, ToolResultBlock, ToolUseBlock

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S | re.I)


def protocol_instructions(tools: Sequence[Mapping[str, Any]]) -> str:
    catalogue = json.dumps(
        [{"name": t["name"], "description": t["description"], "arguments_schema": t["input_schema"]} for t in tools],
        ensure_ascii=False,
    )
    return (
        "## Tool-calling protocol (strict)\n"
        "You can call tools. To call tools, reply with ONLY a JSON object, nothing before or after it:\n"
        '{"tool_calls": [{"name": "<tool name>", "arguments": { ... }}]}\n'
        "You may include several calls in one reply. Tool results come back in the next user message as "
        "[tool_result ...] blocks. When you are done, reply with plain text for the user "
        '(or {"final": "<text>"}). Never put tool-call JSON inside prose. Never invent tool names.\n'
        f"Available tools: {catalogue}"
    )


def render_message_text(m: Message) -> str:
    """Flatten a canonical message to plain text for text-only endpoints."""
    parts: list[str] = []
    for b in m.blocks:
        if isinstance(b, TextBlock):
            parts.append(b.text)
        elif isinstance(b, ToolUseBlock):
            parts.append(json.dumps({"tool_calls": [{"id": b.id, "name": b.name, "arguments": b.arguments}]}, ensure_ascii=False))
        elif isinstance(b, ToolResultBlock):
            status = "error" if b.is_error else "ok"
            parts.append(f'[tool_result id={b.tool_use_id} status={status}]\n{b.content}\n[/tool_result]')
    return "\n".join(parts)


def to_text_messages(messages: Sequence[Message]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": render_message_text(m)} for m in messages]


def to_transcript(messages: Sequence[Message]) -> str:
    tag = {"user": "User", "assistant": "Assistant"}
    return "\n\n".join(f"{tag[m.role]}: {render_message_text(m)}" for m in messages) + "\n\nAssistant:"


def _strip_fence(text: str) -> str:
    t = text.strip()
    m = _FENCE_RE.match(t)
    return m.group(1).strip() if m else t


def parse_reply(text: str, tools: Mapping[str, Mapping[str, Any]]) -> tuple[list[Block], str]:
    """Return (blocks, stop_reason). `tools` maps name -> input_schema."""
    candidate = _strip_fence(text)
    if not candidate.startswith("{"):
        return [TextBlock(text.strip())], "end_turn"
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        # Looks like JSON but is not valid: treat as a protocol violation only if it mentions our keys.
        if '"tool_calls"' in candidate or '"final"' in candidate:
            raise ProviderProtocolError("reply looked like a tool-call object but is not valid JSON") from None
        return [TextBlock(text.strip())], "end_turn"
    if not isinstance(obj, dict):
        return [TextBlock(text.strip())], "end_turn"

    if "tool_calls" in obj:
        calls = obj["tool_calls"]
        if not isinstance(calls, list) or not calls:
            raise ProviderProtocolError("tool_calls must be a non-empty list")
        extra = set(obj) - {"tool_calls", "message"}
        if extra:
            raise ProviderProtocolError(f"unexpected keys alongside tool_calls: {sorted(extra)}")
        blocks: list[Block] = []
        if isinstance(obj.get("message"), str) and obj["message"].strip():
            blocks.append(TextBlock(obj["message"].strip()))
        for i, call in enumerate(calls):
            if not isinstance(call, dict) or not isinstance(call.get("name"), str):
                raise ProviderProtocolError(f"tool_calls[{i}] needs a string 'name'")
            name = call["name"]
            if name not in tools:
                raise ProviderProtocolError(f"tool_calls[{i}]: unknown tool {name!r}")
            args = call.get("arguments", {})
            if not isinstance(args, dict):
                raise ProviderProtocolError(f"tool_calls[{i}]: 'arguments' must be an object")
            errs = validate(args, dict(tools[name]))
            if errs:
                raise ProviderProtocolError(f"tool_calls[{i}] ({name}): " + "; ".join(errs[:4]))
            blocks.append(ToolUseBlock("call_" + uuid.uuid4().hex[:10], name, args))
        return blocks, "tool_use"

    if "final" in obj and isinstance(obj["final"], str) and set(obj) <= {"final"}:
        return [TextBlock(obj["final"].strip())], "end_turn"

    # JSON that is neither shape: treat as ordinary text (it may simply be data the user asked for).
    return [TextBlock(text.strip())], "end_turn"


def repair_prompt(error: str) -> str:
    return (
        f"Your last reply was rejected: {error}. Reply again with ONLY a valid JSON object "
        '{"tool_calls": [...]} using the available tools and their schemas, or with plain text for the user.'
    )
