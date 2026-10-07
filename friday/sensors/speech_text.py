# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Turning text into something worth saying aloud, and transcripts into something safe to act on."""

from __future__ import annotations

import re
import unicodedata

_CODE_BLOCK = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_URL = re.compile(r"https?://\S+", re.I)
_MD_NOISE = re.compile(r"[*_#>~|]+")
_BULLET = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.M)
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def strip_unspeakable(text: str) -> str:
    """Drop control, format (bidi / zero-width), private-use and separator characters; collapse whitespace."""
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in "\n\t":
            out.append(" ")
        elif cat[0] == "C" or cat in ("Zl", "Zp"):
            continue
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def speakable(text: str, max_chars: int = 600, overflow: str = "The rest is on screen.") -> str:
    """Plain, short text for TTS: no code blocks, URLs or markdown; cut at a sentence end if too long."""
    t = _CODE_BLOCK.sub(" (code omitted) ", text or "")
    t = _INLINE_CODE.sub(r"\1", t)
    t = _URL.sub("a link", t)
    t = _BULLET.sub("", t)
    t = _MD_NOISE.sub(" ", t)
    t = strip_unspeakable(t)
    if len(t) <= max_chars:
        return t
    head = t[:max_chars]
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    if ends and ends[-1] > max_chars // 3:
        head = head[: ends[-1]]
    else:
        head = head.rsplit(" ", 1)[0]
    return f"{head.strip()} {overflow}".strip()


_NEGATIVE = {"no", "nope", "nah", "cancel", "stop", "deny", "denied", "negative", "don't", "dont", "not", "abort", "wait", "never", "decline"}


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower().replace("’", "'"))


def is_negative(text: str) -> bool:
    return bool(set(words(text)) & _NEGATIVE)


_FILLER = re.compile(r"^(?:\W|\b(?:uh|um|hmm|mm|ah|oh)\b)*$", re.I)
_HALLUCINATIONS = {"you", "bye", "thank you", "thanks for watching", "thank you for watching", "."}


def meaningful(text: str) -> bool:
    """False for empty transcripts and the filler/hallucination fragments speech models emit on near-silence."""
    t = (text or "").strip()
    if not t or _FILLER.match(t):
        return False
    return t.lower().strip(" .!?,") not in _HALLUCINATIONS
