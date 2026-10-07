# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""SQLite (WAL) wrapper with migrations.

One connection guarded by an RLock: the daemon has concurrent writers (agent loop, scheduler,
sensors) and a single serialized connection is the simplest way to be correct. WAL gives
atomic commits and crash safety; reads never block the UI.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from .errors import StorageError

T = TypeVar("T")

# Each migration is a list of statements applied once, in order. Never edit a shipped migration;
# append a new one.
MIGRATIONS: list[list[str]] = [
    # v1 — kv + append-only audit log
    [
        """CREATE TABLE kv (
               key TEXT PRIMARY KEY,
               value TEXT NOT NULL,
               updated_at REAL NOT NULL
           )""",
        """CREATE TABLE audit (
               seq INTEGER PRIMARY KEY AUTOINCREMENT,
               ts REAL NOT NULL,
               actor TEXT NOT NULL,
               event TEXT NOT NULL,
               data TEXT NOT NULL,
               prev_hash TEXT NOT NULL,
               hash TEXT NOT NULL
           )""",
        """CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit
           BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END""",
        """CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit
           BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END""",
    ],
    # v2 — native memory: long-term memories, rolling conversation summary, turn log
    [
        """CREATE TABLE memories (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               kind TEXT NOT NULL,
               text TEXT NOT NULL,
               tags TEXT NOT NULL DEFAULT '',
               source TEXT NOT NULL,
               provenance TEXT NOT NULL,
               importance REAL NOT NULL DEFAULT 0.5,
               pinned INTEGER NOT NULL DEFAULT 0,
               created_at REAL NOT NULL,
               updated_at REAL NOT NULL,
               last_used REAL,
               use_count INTEGER NOT NULL DEFAULT 0,
               norm TEXT NOT NULL
           )""",
        "CREATE UNIQUE INDEX memories_norm ON memories(norm)",
        """CREATE TABLE summaries (
               session_id TEXT PRIMARY KEY,
               summary TEXT NOT NULL,
               turns_covered INTEGER NOT NULL DEFAULT 0,
               updated_at REAL NOT NULL
           )""",
        """CREATE TABLE turns (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               session_id TEXT NOT NULL,
               ts REAL NOT NULL,
               source TEXT NOT NULL,
               user_text TEXT NOT NULL,
               assistant_text TEXT NOT NULL,
               status TEXT NOT NULL,
               tainted INTEGER NOT NULL DEFAULT 0
           )""",
        "CREATE INDEX turns_session ON turns(session_id, id)",
    ],
    # v3 — local tools: tasks, notes, reminders (alarms), filesystem undo journal
    [
        """CREATE TABLE tasks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               details TEXT NOT NULL DEFAULT '',
               status TEXT NOT NULL DEFAULT 'open',
               priority INTEGER NOT NULL DEFAULT 2,
               due_at REAL,
               created_at REAL NOT NULL,
               updated_at REAL NOT NULL,
               completed_at REAL,
               tainted INTEGER NOT NULL DEFAULT 0
           )""",
        "CREATE INDEX tasks_status ON tasks(status, due_at)",
        """CREATE TABLE notes (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               body TEXT NOT NULL,
               tags TEXT NOT NULL DEFAULT '',
               created_at REAL NOT NULL,
               updated_at REAL NOT NULL,
               tainted INTEGER NOT NULL DEFAULT 0
           )""",
        """CREATE TABLE reminders (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               message TEXT NOT NULL,
               due_at REAL NOT NULL,
               repeat TEXT NOT NULL DEFAULT 'none',
               status TEXT NOT NULL DEFAULT 'pending',
               task_id INTEGER,
               created_at REAL NOT NULL,
               fired_at REAL,
               fire_count INTEGER NOT NULL DEFAULT 0,
               tainted INTEGER NOT NULL DEFAULT 0
           )""",
        "CREATE INDEX reminders_due ON reminders(status, due_at)",
        """CREATE TABLE fs_journal (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               op TEXT NOT NULL,
               src TEXT NOT NULL,
               dst TEXT NOT NULL DEFAULT '',
               backup TEXT NOT NULL DEFAULT '',
               is_dir INTEGER NOT NULL DEFAULT 0,
               size INTEGER NOT NULL DEFAULT 0,
               sig TEXT NOT NULL DEFAULT '',
               ts REAL NOT NULL,
               state TEXT NOT NULL DEFAULT 'active',
               undone_at REAL
           )""",
    ],
]


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # ---- lifecycle ----
    def open(self) -> Database:
        if self._conn is not None:
            return self
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10.0)
            conn.row_factory = sqlite3.Row
            if self.path != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
        except sqlite3.Error as exc:
            raise StorageError(f"cannot open database {self.path}: {exc}") from exc
        self._conn = conn
        try:
            self._migrate()
        except BaseException:
            self.close()          # don't leak the connection when the schema is newer / a migration fails
            raise
        return self

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> Database:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- migrations ----
    def _migrate(self) -> None:
        with self._lock:
            version = self.scalar("PRAGMA user_version") or 0
            if version > len(MIGRATIONS):
                raise StorageError(f"database schema v{version} is newer than this build (v{len(MIGRATIONS)})")
            for idx in range(version, len(MIGRATIONS)):
                with self.transaction() as conn:
                    for stmt in MIGRATIONS[idx]:
                        conn.execute(stmt)
                    conn.execute(f"PRAGMA user_version={idx + 1}")

    # ---- primitives ----
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StorageError("database is not open")
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE ... COMMIT; nested use joins the outer transaction."""
        with self._lock:
            conn = self.conn
            if conn.in_transaction:
                yield conn
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self.conn.execute(sql, params)
            except sqlite3.Error as exc:
                raise StorageError(f"{exc} (sql: {sql[:80]})") from exc

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.execute(sql, params).fetchall())

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        with self._lock:
            row = self.execute(sql, params).fetchone()
            return None if row is None else row[0]

    # ---- kv ----
    def kv_get(self, key: str, default: str | None = None) -> str | None:
        val = self.scalar("SELECT value FROM kv WHERE key=?", (key,))
        return default if val is None else val

    def kv_set(self, key: str, value: str, now: float) -> None:
        self.execute(
            "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now),
        )

    # ---- async helper ----
    async def arun(self, fn: Callable[..., T], *args: Any) -> T:
        """Run a blocking DB function off the event loop."""
        return await asyncio.to_thread(fn, *args)
