# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Code-built confirmation cards (Architecture §6.4).

The model never writes (or influences the formatting of) what you are asked to approve. Every value is
redacted, stripped of control/bidi characters, length-capped, and shown with a hash that binds the
approval to these exact arguments.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Callable
from typing import Any

from .policy import Decision

MAX_VALUE_CHARS = 240


def args_hash(tool: str, args: dict[str, Any]) -> str:
    blob = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sanitize_display(text: str) -> str:
    """Escape control, format (bidi / zero-width) and line-separator characters so values cannot spoof the card."""
    out: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif cat in ("Cc", "Cf", "Zl", "Zp", "Co", "Cs", "Cn"):
            out.append(f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}")
        else:
            out.append(ch)
    return "".join(out)


def _render_value(value: Any, redact: Callable[[str], str]) -> str:
    if isinstance(value, str):
        text = redact(value)
        n = len(value)
        shown = sanitize_display(text)
        if len(shown) > MAX_VALUE_CHARS:
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
            head = shown[: MAX_VALUE_CHARS - 40]
            return f"<{n} chars, sha256:{digest}> '{head}…'"
        return f"'{shown}'"
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    shown = sanitize_display(redact(text))
    return shown if len(shown) <= MAX_VALUE_CHARS else shown[: MAX_VALUE_CHARS - 1] + "…"


MAX_READBACK_CHARS = 420           # longer than this is not read aloud as an approval basis: approve it on screen
_SPOKEN_VALUE_CHARS = 120


def _spoken(value: str, limit: int = _SPOKEN_VALUE_CHARS) -> tuple[str, bool]:
    """Plain words for a voice readback: no control / bidi characters, no line breaks. Returns (text, complete);
    `complete` is False when the value had to be cut, so the caller can refuse a spoken approval."""
    cleaned = "".join(" " if ch in "\n\t" else ch for ch in value if unicodedata.category(ch)[0] != "C" or ch in "\n\t")
    cleaned = " ".join(cleaned.split())
    if len(cleaned) <= limit:
        return cleaned, True
    return cleaned[:limit].rsplit(" ", 1)[0] + " and more", False


def build_readback(tool: str, args: dict[str, Any], decision: Decision, redact: Callable[[str], str]) -> tuple[str, bool]:
    """What FRIDAY says aloud before it accepts a spoken "yes", built by code from the exact arguments, like the card.
    Returns (text, complete). `complete` is False whenever anything was left out (more than 4 arguments, a long value,
    a long list, a nested structure, a long text): the action cannot be fully described by ear, so a spoken approval is
    refused and the request has to be approved on screen. The T3 challenge phrase never appears here."""
    complete = True
    parts: list[str] = []
    keys = sorted(args)
    for key in keys[:4]:
        v = args[key]
        if isinstance(v, str):
            shown, ok = _spoken(redact(v))
        elif isinstance(v, (list, tuple)):
            items = [_spoken(redact(str(x)), 60) for x in v[:3]]
            shown = ", ".join(t for t, _ in items)
            ok = all(o for _, o in items) and len(v) <= 3
            if len(v) > 3:
                shown += " and more"
        elif isinstance(v, dict):
            shown, ok = ("an empty set of options", True) if not v else ("a nested set of options", False)
        elif v is None:
            shown, ok = "nothing", True
        else:
            shown, ok = _spoken(redact(str(v)))
        complete = complete and ok
        name, _ = _spoken(str(key).replace("_", " "), 30)
        parts.append(f"{name}: {shown}")
    tool_said, _ = _spoken(tool.replace("_", " "), 40)
    text = f"I would like to run {tool_said}"
    if parts:
        text += ", with " + "; ".join(parts)
    if len(keys) > 4:
        text += f"; and {len(keys) - 4} more details that are only on screen"
        complete = False
    if decision.resolved_paths:
        names = [p.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] for p in decision.resolved_paths[:2]]
        spoken_names = [_spoken(n, 40)[0] for n in names if n]
        if spoken_names:
            text += ". It touches " + " and ".join(spoken_names)
        if len(decision.resolved_paths) > 2:
            text += f" and {len(decision.resolved_paths) - 2} more"
            complete = False
    if decision.reasons:
        why, ok = _spoken(decision.reasons[0], 120)
        text += ". " + why
        complete = complete and ok
    text += "."
    if len(text) > MAX_READBACK_CHARS:
        complete = False
    return text, complete


def render_readback(tool: str, args: dict[str, Any], decision: Decision, redact: Callable[[str], str]) -> str:
    return build_readback(tool, args, decision, redact)[0]


def render_card(tool: str, args: dict[str, Any], decision: Decision, redact: Callable[[str], str]) -> str:
    lines = [f"FRIDAY wants to run: {sanitize_display(tool)}   [{decision.tier.label}]"]
    if decision.reasons:
        lines.append("Why you're being asked:")
        lines.extend(f"  - {sanitize_display(r)}" for r in decision.reasons)
    lines.append("Arguments:")
    if not args:
        lines.append("  (none)")
    for key in sorted(args):
        lines.append(f"  {sanitize_display(str(key))}: {_render_value(args[key], redact)}")
    if decision.resolved_paths:
        lines.append("Resolved paths:")
        lines.extend(f"  -> {sanitize_display(p)}" for p in decision.resolved_paths)
    lines.append(f"Bound to these exact arguments (hash {args_hash(tool, args)[:12]}).")
    return "\n".join(lines)
