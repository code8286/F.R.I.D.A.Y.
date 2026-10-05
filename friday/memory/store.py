# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""SQLite-backed storage for FRIDAY's memory (tables come from migration v2).

* `memories`  — durable facts / preferences / episodes, deduplicated on a normalised text key.
* `summaries` — one rolling summary per session of conversation that scrolled out of the context window.
* `turns`     — compact log of each exchange (your text + FRIDAY's final reply), used to restore recent
                context after a restart. Tool traffic is deliberately NOT stored here.

Search uses FTS5 (porter stemming, bm25) when this SQLite build has it, and falls back to LIKE matching.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from ..core.db import Database

KINDS = ("fact", "preference", "episode")
PROVENANCE = ("user", "assistant", "approved")
# user      : stated by you (extracted from your own message, or you asked FRIDAY to remember it)
# assistant : FRIDAY chose to save it during a clean (untainted) turn
# approved  : proposed while untrusted content was in context; saved only because you confirmed it

_STOP = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "but", "by", "do", "does", "for", "from", "had", "has", "have", "he", "her", "his", "i", "if", "in", "into", "is", "it", "its", "me", "my", "of", "on", "or", "our", "she", "so", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to", "was", "we", "were", "what", "when", "where", "which", "who", "will", "with", "you", "your"]
)
_TOKEN = re.compile(r"[A-Za-z0-9_]{2,}")


@dataclass
class Memory:
    id: int
    kind: str
    text: str
    tags: str
    source: str
    provenance: str
    importance: float
    pinned: bool
    created_at: float
    updated_at: float
    last_used: float | None
    use_count: int


def normalise(text: str) -> str:
    return " ".join(_TOKEN.findall(text.lower()))


def tokens(text: str) -> list[str]:
    seen: list[str] = []
    for t in _TOKEN.findall(text.lower()):
        if t not in _STOP and t not in seen:
            seen.append(t)
    return seen[:24]


def _row(r: sqlite3.Row) -> Memory:
    return Memory(
        r["id"], r["kind"], r["text"], r["tags"], r["source"], r["provenance"], r["importance"], bool(r["pinned"]),
        r["created_at"], r["updated_at"], r["last_used"], r["use_count"],
    )


class MemoryStore:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time):
        self.db = db
        self._clock = clock
        self.fts = False

    # ------------------------------------------------------------------ setup
    def init(self) -> None:
        """Create the FTS5 index (+ sync triggers) if available. Safe to call every start."""
        try:
            exists = self.db.scalar("SELECT 1 FROM sqlite_master WHERE name='memories_fts'")
            if not exists:
                with self.db.transaction():
                    self.db.execute(
                        "CREATE VIRTUAL TABLE memories_fts USING fts5(text, tags, content='memories', content_rowid='id', "
                        "tokenize='porter unicode61')"
                    )
                    self.db.execute(
                        "CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN "
                        "INSERT INTO memories_fts(rowid, text, tags) VALUES (new.id, new.text, new.tags); END"
                    )
                    self.db.execute(
                        "CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN "
                        "INSERT INTO memories_fts(memories_fts, rowid, text, tags) VALUES ('delete', old.id, old.text, old.tags); END"
                    )
                    self.db.execute(
                        "CREATE TRIGGER memories_au AFTER UPDATE OF text, tags ON memories BEGIN "
                        "INSERT INTO memories_fts(memories_fts, rowid, text, tags) VALUES ('delete', old.id, old.text, old.tags); "
                        "INSERT INTO memories_fts(rowid, text, tags) VALUES (new.id, new.text, new.tags); END"
                    )
                    self.db.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')")
            self.fts = True
        except Exception:  # FTS5 not compiled in, or table is damaged: degrade to LIKE search
            self.fts = False

    # ------------------------------------------------------------------ memories
    def add(
        self, *, kind: str, text: str, tags: Sequence[str] = (), source: str, provenance: str,
        importance: float = 0.5, pinned: bool = False,
    ) -> tuple[int, bool]:
        """Insert, or merge into an existing memory with the same normalised text. Returns (id, created)."""
        now = self._clock()
        norm = normalise(text)
        tag_s = ",".join(t.strip().lower() for t in tags if t.strip())[:200]
        with self.db.transaction():
            row = self.db.query("SELECT id, importance, pinned FROM memories WHERE norm=?", (norm,))
            if row:
                r = row[0]
                self.db.execute(
                    "UPDATE memories SET importance=?, pinned=?, updated_at=? WHERE id=?",
                    (max(r["importance"], importance), int(bool(r["pinned"]) or pinned), now, r["id"]),
                )
                return r["id"], False
            cur = self.db.execute(
                "INSERT INTO memories(kind,text,tags,source,provenance,importance,pinned,created_at,updated_at,norm) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (kind, text, tag_s, source, provenance, importance, int(pinned), now, now, norm),
            )
            return int(cur.lastrowid), True

    def get(self, mem_id: int) -> Memory | None:
        rows = self.db.query("SELECT * FROM memories WHERE id=?", (mem_id,))
        return _row(rows[0]) if rows else None

    def delete(self, mem_id: int) -> bool:
        with self.db.transaction():
            cur = self.db.execute("DELETE FROM memories WHERE id=?", (mem_id,))
            return cur.rowcount > 0

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM memories") or 0)

    def recent(self, n: int = 20) -> list[Memory]:
        return [_row(r) for r in self.db.query("SELECT * FROM memories ORDER BY updated_at DESC, id DESC LIMIT ?", (n,))]

    def pinned(self, n: int = 5) -> list[Memory]:
        return [_row(r) for r in self.db.query("SELECT * FROM memories WHERE pinned=1 ORDER BY importance DESC, id ASC LIMIT ?", (n,))]

    def set_pinned(self, mem_id: int, pinned: bool) -> bool:
        with self.db.transaction():
            return self.db.execute("UPDATE memories SET pinned=? WHERE id=?", (int(pinned), mem_id)).rowcount > 0

    def search(self, query: str, limit: int = 20) -> list[Memory]:
        return [m for m, _ in self.search_scored(query, limit)]

    def search_scored(self, query: str, limit: int = 20) -> list[tuple[Memory, float]]:
        """Candidates best-first with a relevance score in (0, 1] (1 = best match in this result set)."""
        toks = tokens(query)
        if not toks:
            return []
        if self.fts:
            match = " OR ".join(f'"{t}"' for t in toks)
            try:
                rows = self.db.query(
                    "SELECT m.*, bm25(memories_fts) AS score FROM memories_fts f JOIN memories m ON m.id = f.rowid "
                    "WHERE memories_fts MATCH ? ORDER BY score LIMIT ?",
                    (match, limit),
                )
                if not rows:
                    return []
                scores = [r["score"] for r in rows]          # bm25: lower (more negative) = better
                best, worst = min(scores), max(scores)
                span = worst - best
                return [(_row(r), 1.0 if span < 1e-9 else 1.0 - 0.8 * (r["score"] - best) / span) for r in rows]
            except Exception:
                pass  # fall through to LIKE
        clauses = " + ".join("(CASE WHEN norm LIKE ? THEN 1 ELSE 0 END)" for _ in toks)
        rows = self.db.query(
            f"SELECT *, ({clauses}) AS hits FROM memories WHERE hits > 0 ORDER BY hits DESC, updated_at DESC LIMIT ?",
            [f"%{t}%" for t in toks] + [limit],
        )
        top = max((r["hits"] for r in rows), default=1)
        return [(_row(r), r["hits"] / top) for r in rows]

    def touch(self, ids: Iterable[int]) -> None:
        now = self._clock()
        ids = list(ids)
        if ids:
            with self.db.transaction():
                for i in ids:
                    self.db.execute("UPDATE memories SET last_used=?, use_count=use_count+1 WHERE id=?", (now, i))

    def prune(self, max_memories: int) -> int:
        """Drop the lowest-value unpinned memories above the cap (value = importance, then use, then age)."""
        over = self.count() - max_memories
        if over <= 0:
            return 0
        with self.db.transaction():
            ids = [
                r["id"]
                for r in self.db.query(
                    "SELECT id FROM memories WHERE pinned=0 ORDER BY importance ASC, use_count ASC, updated_at ASC LIMIT ?",
                    (over,),
                )
            ]
            for i in ids:
                self.db.execute("DELETE FROM memories WHERE id=?", (i,))
        return len(ids)

    # ------------------------------------------------------------------ summaries
    def get_summary(self, session_id: str) -> str | None:
        return self.db.scalar("SELECT summary FROM summaries WHERE session_id=?", (session_id,))

    def set_summary(self, session_id: str, summary: str, turns_covered: int) -> None:
        self.db.execute(
            "INSERT INTO summaries(session_id, summary, turns_covered, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET summary=excluded.summary, "
            "turns_covered=summaries.turns_covered + excluded.turns_covered, updated_at=excluded.updated_at",
            (session_id, summary, turns_covered, self._clock()),
        )

    # ------------------------------------------------------------------ turn log
    def log_turn(self, session_id: str, source: str, user_text: str, assistant_text: str, status: str, tainted: bool) -> int:
        cur = self.db.execute(
            "INSERT INTO turns(session_id, ts, source, user_text, assistant_text, status, tainted) VALUES(?,?,?,?,?,?,?)",
            (session_id, self._clock(), source, user_text, assistant_text, status, int(tainted)),
        )
        return int(cur.lastrowid)

    def recent_turns(self, session_id: str, n: int) -> list[sqlite3.Row]:
        rows = self.db.query("SELECT * FROM turns WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, n))
        return list(reversed(rows))

    def purge_old_turns(self, days: int) -> int:
        cutoff = self._clock() - days * 86400
        with self.db.transaction():
            return self.db.execute("DELETE FROM turns WHERE ts < ?", (cutoff,)).rowcount
