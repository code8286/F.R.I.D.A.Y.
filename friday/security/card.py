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
