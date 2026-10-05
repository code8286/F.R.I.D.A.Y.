# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Minimal TOML-subset parser, used ONLY when neither `tomllib` (3.11+) nor `tomli` is importable.

Supports exactly what FRIDAY's config uses: comments, [tables] (dotted ok), `key = value` with basic and
literal strings, integers, floats, booleans and single-line arrays of those. Anything else raises
`TOMLDecodeError` rather than being silently misread.
"""

from __future__ import annotations

import re
from typing import Any


class TOMLDecodeError(ValueError):
    pass


_BARE = re.compile(r"^[A-Za-z0-9_-]+$")
_INT = re.compile(r"^[+-]?\d+(_\d+)*$")
_FLOAT = re.compile(r"^[+-]?\d+(_\d+)*(\.\d+(_\d+)*)?([eE][+-]?\d+)?$")
_ESC = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}


def _err(lineno: int, msg: str) -> TOMLDecodeError:
    return TOMLDecodeError(f"line {lineno}: {msg}")


def _strip_comment(line: str) -> str:
    quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote == '"':
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = None
        elif quote == "'":
            if ch == "'":
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
        i += 1
    return line


def _parse_string(s: str, lineno: int) -> tuple[str, int]:
    """Parse a string literal at s[0]; return (value, index just past the closing quote)."""
    q = s[0]
    if s.startswith(q * 3):
        raise _err(lineno, "multi-line strings are not supported")
    out: list[str] = []
    i = 1
    while i < len(s):
        ch = s[i]
        if q == "'":
            if ch == "'":
                return "".join(out), i + 1
            out.append(ch)
        else:
            if ch == '"':
                return "".join(out), i + 1
            if ch == "\\":
                i += 1
                if i >= len(s):
                    break
                esc = s[i]
                if esc in _ESC:
                    out.append(_ESC[esc])
                elif esc in "uU":
                    n = 4 if esc == "u" else 8
                    hexs = s[i + 1 : i + 1 + n]
                    if len(hexs) != n:
                        raise _err(lineno, "bad unicode escape")
                    try:
                        out.append(chr(int(hexs, 16)))
                    except ValueError:
                        raise _err(lineno, "bad unicode escape") from None
                    i += n
                else:
                    raise _err(lineno, f"invalid escape \\{esc}")
            else:
                out.append(ch)
        i += 1
    raise _err(lineno, "unterminated string")


def _split_array(inner: str, lineno: int) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    cur: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            cur.append(ch)
            if quote == '"' and ch == "\\" and i + 1 < len(inner):
                i += 1
                cur.append(inner[i])
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == "[":
            depth += 1
            cur.append(ch)
        elif ch == "]":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    if quote or depth:
        raise _err(lineno, "unterminated array")
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_value(s: str, lineno: int) -> Any:
    s = s.strip()
    if not s:
        raise _err(lineno, "missing value")
    if s[0] in "\"'":
        value, end = _parse_string(s, lineno)
        if s[end:].strip():
            raise _err(lineno, "unexpected text after string")
        return value
    if s == "true":
        return True
    if s == "false":
        return False
    if s[0] == "[":
        if not s.endswith("]"):
            raise _err(lineno, "multi-line arrays are not supported")
        return [_parse_value(p, lineno) for p in _split_array(s[1:-1], lineno)]
    if _INT.match(s):
        return int(s.replace("_", ""))
    if _FLOAT.match(s):
        return float(s.replace("_", ""))
    raise _err(lineno, f"unsupported value {s!r}")


def _parse_key(raw: str, lineno: int) -> str:
    raw = raw.strip()
    if raw and raw[0] in "\"'":
        value, end = _parse_string(raw, lineno)
        if raw[end:].strip():
            raise _err(lineno, "bad key")
        return value
    if not _BARE.match(raw):
        raise _err(lineno, f"bad key {raw!r}")
    return raw


def loads(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    cur = root
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[["):
            raise _err(lineno, "arrays of tables are not supported")
        if line.startswith("["):
            if not line.endswith("]"):
                raise _err(lineno, "bad table header")
            cur = root
            for part in line[1:-1].split("."):
                key = _parse_key(part, lineno)
                nxt = cur.setdefault(key, {})
                if not isinstance(nxt, dict):
                    raise _err(lineno, f"{key!r} is not a table")
                cur = nxt
            continue
        key_raw, eq, val_raw = line.partition("=")
        if not eq:
            raise _err(lineno, "expected key = value")
        key = _parse_key(key_raw, lineno)
        if key in cur:
            raise _err(lineno, f"duplicate key {key!r}")
        cur[key] = _parse_value(val_raw, lineno)
    return root
