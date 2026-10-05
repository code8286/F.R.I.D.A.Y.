# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Append-only, hash-chained audit log stored in SQLite.

Each record's hash covers (seq, ts, actor, event, data, prev_hash). SQLite triggers reject UPDATE and
DELETE; `verify()` recomputes the chain so tampering (including by someone who drops the triggers)
is detected. If an HMAC key (kept in the OS keyring) is supplied, hashes are keyed, so rewriting the
whole chain without the key is impossible; a keyed *anchor* of the tail also detects truncation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .db import Database
from .errors import AuditIntegrityError

GENESIS = "0" * 64
ANCHOR_KEY = "audit.anchor"


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    ts: float
    actor: str
    event: str
    data: dict[str, Any]
    prev_hash: str
    hash: str


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    records: int
    error: str | None = None
    bad_seq: int | None = None


class AuditLog:
    def __init__(
        self,
        db: Database,
        hmac_key: bytes | None = None,
        redact: Callable[[Any], Any] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.db = db
        self._key = hmac_key
        self._redact = redact
        self._clock = clock

    # ---- hashing ----
    def _digest(self, payload: str) -> str:
        if self._key:
            return hmac.new(self._key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _hash(self, seq: int, ts: float, actor: str, event: str, data_json: str, prev: str) -> str:
        return self._digest(_canonical([seq, repr(ts), actor, event, data_json, prev]))

    def _anchor(self, seq: int, hash_: str) -> str:
        return self._digest(f"anchor:{seq}:{hash_}")

    # ---- write ----
    def append(self, actor: str, event: str, data: dict[str, Any] | None = None) -> AuditRecord:
        payload = data or {}
        if self._redact:
            payload = self._redact(payload)
        data_json = _canonical(payload)
        ts = self._clock()
        with self.db.transaction():
            last = self.db.query("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1")
            prev = last[0]["hash"] if last else GENESIS
            seq = (last[0]["seq"] + 1) if last else 1
            # Force the sequence number so the hash can cover it.
            hash_ = self._hash(seq, ts, actor, event, data_json, prev)
            self.db.execute(
                "INSERT INTO audit(seq, ts, actor, event, data, prev_hash, hash) VALUES(?,?,?,?,?,?,?)",
                (seq, ts, actor, event, data_json, prev, hash_),
            )
            self.db.kv_set(ANCHOR_KEY, f"{seq}:{self._anchor(seq, hash_)}", ts)
        return AuditRecord(seq, ts, actor, event, json.loads(data_json), prev, hash_)

    # ---- read / verify ----
    def tail(self, n: int = 20) -> list[AuditRecord]:
        rows = self.db.query("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (n,))
        return [
            AuditRecord(r["seq"], r["ts"], r["actor"], r["event"], json.loads(r["data"]), r["prev_hash"], r["hash"])
            for r in reversed(rows)
        ]

    def verify(self) -> VerifyResult:
        prev = GENESIS
        expected_seq = 1
        count = 0
        last_hash = GENESIS
        for row in self.db.query("SELECT * FROM audit ORDER BY seq ASC"):
            if row["seq"] != expected_seq:
                return VerifyResult(False, count, f"sequence gap before #{row['seq']}", row["seq"])
            if row["prev_hash"] != prev:
                return VerifyResult(False, count, f"broken chain at #{row['seq']}", row["seq"])
            want = self._hash(row["seq"], row["ts"], row["actor"], row["event"], row["data"], row["prev_hash"])
            if not hmac.compare_digest(want, row["hash"]):
                return VerifyResult(False, count, f"hash mismatch at #{row['seq']}", row["seq"])
            prev = row["hash"]
            last_hash = row["hash"]
            expected_seq += 1
            count += 1
        anchor = self.db.kv_get(ANCHOR_KEY)
        if count:
            want_anchor = f"{count}:{self._anchor(count, last_hash)}"
            if anchor != want_anchor:
                return VerifyResult(False, count, "tail anchor mismatch (log truncated or rewritten)", count)
        elif anchor:
            return VerifyResult(False, 0, "audit log is empty but an anchor exists (log truncated)", 0)
        return VerifyResult(True, count)

    def assert_intact(self) -> None:
        res = self.verify()
        if not res.ok:
            raise AuditIntegrityError(res.error or "audit chain invalid")
