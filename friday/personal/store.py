# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""SQLite stores for tasks, notes and reminders (migration v3).

Text stored here is user data. It can still contain words that came from a web page on a turn the user
approved, so tool output from these stores is enveloped as RECALLED data and never placed in the system prompt.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from ..core.db import Database
from ..core.errors import ToolError

Clock = Callable[[], float]

STATUSES = ("open", "done")
REPEATS = ("none", "hourly", "daily", "weekdays", "weekly")


# --------------------------------------------------------------------------- time helpers
def parse_when(text: str, tz: tzinfo, now: float) -> float:
    """Parse an ISO-8601 date/time (naive values are in the user's timezone) into epoch seconds."""
    s = text.strip()
    if not s:
        raise ToolError("empty date/time")
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s += "T09:00:00"                      # a bare date means 09:00 that day
    try:
        dt = datetime.fromisoformat(s.replace(" ", "T", 1) if " " in s and "T" not in s else s)
    except ValueError as exc:
        raise ToolError(f"cannot read {text!r} as a date/time; use ISO 8601 like 2026-10-07T18:30") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    try:
        ts = dt.timestamp()
    except (OverflowError, OSError, ValueError) as exc:
        raise ToolError(f"{text!r} is out of range") from exc
    if not (now - 50 * 365 * 86400 <= ts <= now + 30 * 365 * 86400):
        raise ToolError(f"{text!r} is too far in the past or future (limit: 30 years ahead)")
    return ts


def next_occurrence(due: float, repeat: str, tz: tzinfo, after: float) -> float | None:
    """The first occurrence of a repeating reminder strictly after `after` (None for one-shot reminders)."""
    if repeat == "none":
        return None
    base = datetime.fromtimestamp(due, tz)
    cur = base
    for _ in range(100000):                  # bounded: a reminder that slept for years still terminates
        if repeat == "hourly":
            cur = cur + timedelta(hours=1)
        elif repeat == "daily":
            cur = cur + timedelta(days=1)
        elif repeat == "weekly":
            cur = cur + timedelta(days=7)
        elif repeat == "weekdays":
            cur = cur + timedelta(days=1)
            while cur.weekday() >= 5:
                cur = cur + timedelta(days=1)
        else:
            return None
        if cur.timestamp() > after:
            return cur.timestamp()
    return after + 86400


def fmt_when(ts: float | None, tz: tzinfo) -> str:
    if ts is None:
        return "-"
    try:
        return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M %Z").strip()
    except (OverflowError, OSError, ValueError):
        return "(invalid date)"


# --------------------------------------------------------------------------- tasks
@dataclass(frozen=True)
class Task:
    id: int
    title: str
    details: str
    status: str
    priority: int
    due_at: float | None
    created_at: float
    completed_at: float | None
    tainted: bool = False       # written during a turn that contained untrusted content: shown to the model as data


def _task(r) -> Task:
    return Task(r["id"], r["title"], r["details"], r["status"], r["priority"], r["due_at"], r["created_at"],
                r["completed_at"], bool(r["tainted"]))


class TaskStore:
    def __init__(self, db: Database, clock: Clock = time.time):
        self.db, self._clock = db, clock

    def add(self, title: str, details: str = "", priority: int = 2, due_at: float | None = None, tainted: bool = False) -> int:
        now = self._clock()
        cur = self.db.execute(
            "INSERT INTO tasks(title,details,priority,due_at,created_at,updated_at,tainted) VALUES(?,?,?,?,?,?,?)",
            (title.strip(), details.strip(), priority, due_at, now, now, int(tainted)),
        )
        return int(cur.lastrowid)

    def get(self, task_id: int) -> Task | None:
        rows = self.db.query("SELECT * FROM tasks WHERE id=?", (task_id,))
        return _task(rows[0]) if rows else None

    def list(self, status: str = "open", limit: int = 50) -> list[Task]:
        where, params = "", []
        if status in STATUSES:
            where, params = "WHERE status=?", [status]
        rows = self.db.query(
            f"SELECT * FROM tasks {where} ORDER BY (due_at IS NULL), due_at, priority, id LIMIT ?", (*params, limit)
        )
        return [_task(r) for r in rows]

    def update(self, task_id: int, tainted: bool = False, **fields) -> bool:
        allowed = {"title", "details", "priority", "due_at", "status"}
        sets, params = [], []
        if tainted and set(fields) & {"title", "details"}:
            sets.append("tainted=1")                       # sticky: once untrusted text got in, the row stays data
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(k)
            sets.append(f"{k}=?")
            params.append(v)
        if not sets:
            return self.get(task_id) is not None
        now = self._clock()
        sets.append("updated_at=?")
        params.append(now)
        if fields.get("status") == "done":
            sets.append("completed_at=?")
            params.append(now)
        elif fields.get("status") == "open":
            sets.append("completed_at=NULL")
        cur = self.db.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", (*params, task_id))
        return cur.rowcount > 0

    def delete(self, task_id: int) -> bool:
        cur = self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.db.execute("UPDATE reminders SET task_id=NULL WHERE task_id=?", (task_id,))
        return cur.rowcount > 0

    def counts(self) -> tuple[int, int]:
        """(open, overdue)"""
        now = self._clock()
        open_n = self.db.scalar("SELECT COUNT(*) FROM tasks WHERE status='open'") or 0
        overdue = self.db.scalar("SELECT COUNT(*) FROM tasks WHERE status='open' AND due_at IS NOT NULL AND due_at<?", (now,)) or 0
        return int(open_n), int(overdue)


# --------------------------------------------------------------------------- notes
@dataclass(frozen=True)
class Note:
    id: int
    title: str
    body: str
    tags: tuple[str, ...]
    created_at: float
    updated_at: float
    tainted: bool = False


def _note(r) -> Note:
    tags = tuple(t for t in (r["tags"] or "").split(",") if t)
    return Note(r["id"], r["title"], r["body"], tags, r["created_at"], r["updated_at"], bool(r["tainted"]))


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class NoteStore:
    def __init__(self, db: Database, clock: Clock = time.time):
        self.db, self._clock = db, clock

    def add(self, title: str, body: str, tags: list[str] | None = None, tainted: bool = False) -> int:
        now = self._clock()
        cur = self.db.execute(
            "INSERT INTO notes(title,body,tags,created_at,updated_at,tainted) VALUES(?,?,?,?,?,?)",
            (title.strip(), body, _tags(tags), now, now, int(tainted)),
        )
        return int(cur.lastrowid)

    def get(self, note_id: int) -> Note | None:
        rows = self.db.query("SELECT * FROM notes WHERE id=?", (note_id,))
        return _note(rows[0]) if rows else None

    def list(self, limit: int = 30) -> list[Note]:
        return [_note(r) for r in self.db.query("SELECT * FROM notes ORDER BY updated_at DESC, id DESC LIMIT ?", (limit,))]

    def search(self, query: str, limit: int = 20) -> list[Note]:
        like = _like(query.strip())
        rows = self.db.query(
            "SELECT * FROM notes WHERE title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' "
            "ORDER BY updated_at DESC LIMIT ?",
            (like, like, like, limit),
        )
        return [_note(r) for r in rows]

    def update(self, note_id: int, *, title: str | None = None, body: str | None = None, append: str | None = None,
               tags: list[str] | None = None, tainted: bool = False) -> bool:
        cur = self.get(note_id)
        if cur is None:
            return False
        new_body = body if body is not None else cur.body
        if append:
            new_body = (new_body.rstrip("\n") + "\n" + append) if new_body else append
        self.db.execute(
            "UPDATE notes SET title=?, body=?, tags=?, updated_at=?, tainted=? WHERE id=?",
            (title.strip() if title is not None else cur.title, new_body,
             _tags(tags) if tags is not None else ",".join(cur.tags), self._clock(),
             int(cur.tainted or (tainted and (body is not None or bool(append) or title is not None))), note_id),
        )
        return True

    def delete(self, note_id: int) -> bool:
        return self.db.execute("DELETE FROM notes WHERE id=?", (note_id,)).rowcount > 0

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM notes") or 0)


def _tags(tags: list[str] | None) -> str:
    clean: list[str] = []
    for t in tags or []:
        t = re.sub(r"[^\w\-]+", "-", str(t).strip().lower()).strip("-")[:30]
        if t and t not in clean:
            clean.append(t)
    return ",".join(clean[:8])


# --------------------------------------------------------------------------- reminders
@dataclass(frozen=True)
class Reminder:
    id: int
    message: str
    due_at: float
    repeat: str
    status: str
    task_id: int | None
    created_at: float
    fired_at: float | None
    fire_count: int
    tainted: bool = False


def _rem(r) -> Reminder:
    return Reminder(r["id"], r["message"], r["due_at"], r["repeat"], r["status"], r["task_id"], r["created_at"],
                    r["fired_at"], r["fire_count"], bool(r["tainted"]))


class ReminderStore:
    def __init__(self, db: Database, clock: Clock = time.time):
        self.db, self._clock = db, clock

    def add(self, message: str, due_at: float, repeat: str = "none", task_id: int | None = None, tainted: bool = False) -> int:
        cur = self.db.execute(
            "INSERT INTO reminders(message,due_at,repeat,task_id,created_at,tainted) VALUES(?,?,?,?,?,?)",
            (message.strip(), due_at, repeat, task_id, self._clock(), int(tainted)),
        )
        return int(cur.lastrowid)

    def get(self, rid: int) -> Reminder | None:
        rows = self.db.query("SELECT * FROM reminders WHERE id=?", (rid,))
        return _rem(rows[0]) if rows else None

    def pending(self, limit: int = 100) -> list[Reminder]:
        return [_rem(r) for r in self.db.query(
            "SELECT * FROM reminders WHERE status='pending' ORDER BY due_at, id LIMIT ?", (limit,))]

    def pending_count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM reminders WHERE status='pending'") or 0)

    def recent_fired(self, limit: int = 10) -> list[Reminder]:
        return [_rem(r) for r in self.db.query(
            "SELECT * FROM reminders WHERE status='fired' ORDER BY fired_at DESC LIMIT ?", (limit,))]

    def due(self, now: float, limit: int = 50) -> list[Reminder]:
        return [_rem(r) for r in self.db.query(
            "SELECT * FROM reminders WHERE status='pending' AND due_at<=? ORDER BY due_at, id LIMIT ?", (now, limit))]

    def next_due_at(self) -> float | None:
        return self.db.scalar("SELECT MIN(due_at) FROM reminders WHERE status='pending'")

    def mark_fired(self, rid: int, now: float, next_due: float | None) -> None:
        if next_due is None:
            self.db.execute("UPDATE reminders SET status='fired', fired_at=?, fire_count=fire_count+1 WHERE id=?", (now, rid))
        else:
            self.db.execute(
                "UPDATE reminders SET due_at=?, fired_at=?, fire_count=fire_count+1 WHERE id=?", (next_due, now, rid))

    def cancel(self, rid: int) -> bool:
        return self.db.execute(
            "UPDATE reminders SET status='cancelled' WHERE id=? AND status='pending'", (rid,)).rowcount > 0

    def snooze(self, rid: int, due_at: float) -> bool:
        return self.db.execute(
            "UPDATE reminders SET due_at=?, status='pending' WHERE id=? AND status IN ('pending','fired')", (due_at, rid)
        ).rowcount > 0
