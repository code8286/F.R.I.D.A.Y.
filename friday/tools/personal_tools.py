# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Tasks, notes and reminders/alarms.

Tiers: reading is T0; adding or updating your own task/note/reminder data is T1 (auto on a clean turn, and the policy
engine forces approval when the turn contains untrusted content); replacing a note's whole body is T2; deleting is T2.
Output is RECALLED: enveloped as data, but it does not taint the turn.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..brain.context_builder import _tz
from ..core.config import Config
from ..core.errors import ToolError
from ..personal.scheduler import Scheduler
from ..personal.store import (
    REPEATS,
    NoteStore,
    ReminderStore,
    TaskStore,
    fmt_when,
    parse_when,
)
from ..security.taint import Trust
from ..security.tiers import RiskTier
from .registry import ToolContext, ToolOutput, ToolRegistry


def _data_flag(rows: Any) -> bool | None:
    """Rows written while untrusted content was in the turn come back as untrusted data (and taint); the rest stay RECALLED."""
    return True if any(getattr(r, "tainted", False) for r in rows) else None


DUE_DESC = "ISO 8601 date/time in the user's timezone, e.g. 2026-10-07T18:30 (a bare date means 09:00)"


def register_personal_tools(
    registry: ToolRegistry,
    cfg: Config,
    db: Any,
    scheduler: Scheduler | None,
    *,
    tasks: bool = True,
    notes: bool = True,
    reminders: bool = True,
    clock: Any = time.time,
) -> dict[str, Any]:
    tz = _tz(cfg.conversation.timezone)
    t_store, n_store, r_store = TaskStore(db, clock), NoteStore(db, clock), ReminderStore(db, clock)
    workspace = cfg.workspace

    def when(text: str) -> float:
        return parse_when(text, tz, clock())

    # ------------------------------------------------------------------ tasks
    def task_line(t: Any) -> str:
        due = f", due {fmt_when(t.due_at, tz)}" if t.due_at else ""
        return f"#{t.id} [{t.status}] P{t.priority} {t.title}{due}" + (f"\n    {t.details}" if t.details else "")

    if tasks:
        @registry.tool(
            name="task_add",
            description="Add a to-do item to the user's task list. Use when the user asks you to add, track or remember a "
                        "task. Priority 1 is highest, 3 lowest.",
            schema={"type": "object", "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "details": {"type": "string", "maxLength": 2000},
                "priority": {"type": "integer", "minimum": 1, "maximum": 3},
                "due": {"type": "string", "maxLength": 40, "description": DUE_DESC},
            }, "required": ["title"]},
            tier=RiskTier.T1, rate_limit_per_min=30,
        )
        def task_add(ctx: ToolContext, title: str, details: str = "", priority: int = 2, due: str | None = None) -> str:
            due_at = when(due) if due else None
            tid = t_store.add(title, details, priority, due_at, tainted=ctx.tainted)
            return f"Added task #{tid}: {title}" + (f" (due {fmt_when(due_at, tz)})" if due_at else "")

        @registry.tool(
            name="task_list",
            description="List the user's tasks (default: open ones, soonest due first). Use for 'what's on my list', "
                        "'what's due', or before updating a task so you have its id.",
            schema={"type": "object", "properties": {
                "status": {"type": "string", "enum": ["open", "done", "all"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            }},
            tier=RiskTier.T0, output_trust=Trust.RECALLED,
        )
        def task_list(ctx: ToolContext, status: str = "open", limit: int = 30) -> ToolOutput:
            rows = t_store.list(status, limit)
            if not rows:
                return ToolOutput(f"No {status if status != 'all' else ''} tasks.".replace("  ", " "), source="tasks")
            return ToolOutput("\n".join(task_line(t) for t in rows), source="tasks", untrusted=_data_flag(rows))

        @registry.tool(
            name="task_update",
            description="Change a task: mark it done (status 'done') or reopen it, rename it, or change its details, "
                        "priority or due date. Use task_list first to get the id.",
            schema={"type": "object", "properties": {
                "id": {"type": "integer", "minimum": 1},
                "status": {"type": "string", "enum": ["open", "done"]},
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "details": {"type": "string", "maxLength": 2000},
                "priority": {"type": "integer", "minimum": 1, "maximum": 3},
                "due": {"type": "string", "maxLength": 40, "description": DUE_DESC},
                "clear_due": {"type": "boolean"},
            }, "required": ["id"]},
            tier=RiskTier.T1, rate_limit_per_min=60,
        )
        def task_update(ctx: ToolContext, id: int, **kw: Any) -> str:
            fields: dict[str, Any] = {k: kw[k] for k in ("status", "title", "details", "priority") if k in kw}
            if kw.get("due"):
                fields["due_at"] = when(kw["due"])
            elif kw.get("clear_due"):
                fields["due_at"] = None
            if not fields:
                raise ToolError("nothing to change; give at least one field")
            if not t_store.update(id, tainted=ctx.tainted, **fields):
                raise ToolError(f"no task #{id}")
            return f"Updated task #{id}."

        @registry.tool(
            name="task_delete",
            description="Permanently delete a task by id. Prefer task_update with status 'done' unless the user wants it "
                        "gone.",
            schema={"type": "object", "properties": {"id": {"type": "integer", "minimum": 1}}, "required": ["id"]},
            tier=RiskTier.T2,
        )
        def task_delete(ctx: ToolContext, id: int) -> str:
            return f"Deleted task #{id}." if t_store.delete(id) else f"No task #{id}."

    # ------------------------------------------------------------------ notes
    def note_head(n: Any) -> str:
        tags = f"  [{', '.join(n.tags)}]" if n.tags else ""
        return f"#{n.id} {n.title}{tags} (updated {fmt_when(n.updated_at, tz)})"

    if notes:
        @registry.tool(
            name="note_add",
            description="Save a note for the user (ideas, meeting notes, snippets, things to look at later).",
            schema={"type": "object", "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "body": {"type": "string", "maxLength": 20000},
                "tags": {"type": "array", "items": {"type": "string", "maxLength": 30}, "maxItems": 8},
            }, "required": ["title", "body"]},
            tier=RiskTier.T1, rate_limit_per_min=30,
        )
        def note_add(ctx: ToolContext, title: str, body: str, tags: list | None = None) -> str:
            return f"Saved note #{n_store.add(title, body, tags, tainted=ctx.tainted)}: {title}"

        @registry.tool(
            name="note_list",
            description="List the user's most recently updated notes (titles only). Use note_read for the full text.",
            schema={"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}},
            tier=RiskTier.T0, output_trust=Trust.RECALLED,
        )
        def note_list(ctx: ToolContext, limit: int = 20) -> ToolOutput:
            rows = n_store.list(limit)
            return ToolOutput("\n".join(note_head(n) for n in rows) or "No notes yet.", source="notes", untrusted=_data_flag(rows))

        @registry.tool(
            name="note_search",
            description="Search the user's notes by words in the title, body or tags.",
            schema={"type": "object", "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 100},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            }, "required": ["query"]},
            tier=RiskTier.T0, output_trust=Trust.RECALLED,
        )
        def note_search(ctx: ToolContext, query: str, limit: int = 10) -> ToolOutput:
            rows = n_store.search(query, limit)
            out = []
            for n in rows:
                i = n.body.lower().find(query.lower())
                snippet = n.body[max(0, i - 40): i + 120].replace("\n", " ") if i >= 0 else n.body[:120].replace("\n", " ")
                out.append(f"{note_head(n)}\n    …{snippet}…")
            return ToolOutput("\n".join(out) or "No matching notes.", source="notes", untrusted=_data_flag(rows))

        @registry.tool(
            name="note_read",
            description="Read one note in full by id.",
            schema={"type": "object", "properties": {"id": {"type": "integer", "minimum": 1}}, "required": ["id"]},
            tier=RiskTier.T0, output_trust=Trust.RECALLED,
        )
        def note_read(ctx: ToolContext, id: int) -> ToolOutput:
            n = n_store.get(id)
            if n is None:
                raise ToolError(f"no note #{id}")
            return ToolOutput(f"{note_head(n)}\n\n{n.body}", source="notes", untrusted=_data_flag([n]))

        def note_update_class(args: dict[str, Any]) -> tuple[RiskTier, str] | None:
            if "body" in args:
                return RiskTier.T2, "replaces the whole text of an existing note"
            return None

        @registry.tool(
            name="note_update",
            description="Edit a note: append text to it (preferred), rename it, retag it, or replace its whole text.",
            schema={"type": "object", "properties": {
                "id": {"type": "integer", "minimum": 1},
                "append": {"type": "string", "maxLength": 20000},
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "body": {"type": "string", "maxLength": 20000},
                "tags": {"type": "array", "items": {"type": "string", "maxLength": 30}, "maxItems": 8},
            }, "required": ["id"]},
            tier=RiskTier.T1, classifier=note_update_class, rate_limit_per_min=30,
        )
        def note_update(ctx: ToolContext, id: int, **kw: Any) -> str:
            if not any(k in kw for k in ("append", "title", "body", "tags")):
                raise ToolError("nothing to change")
            if not n_store.update(id, title=kw.get("title"), body=kw.get("body"), append=kw.get("append"), tags=kw.get("tags"),
                                  tainted=ctx.tainted):
                raise ToolError(f"no note #{id}")
            return f"Updated note #{id}."

        @registry.tool(
            name="note_delete",
            description="Permanently delete a note by id.",
            schema={"type": "object", "properties": {"id": {"type": "integer", "minimum": 1}}, "required": ["id"]},
            tier=RiskTier.T2,
        )
        def note_delete(ctx: ToolContext, id: int) -> str:
            return f"Deleted note #{id}." if n_store.delete(id) else f"No note #{id}."

        @registry.tool(
            name="note_export",
            description="Export a note (or all notes when no id is given) as Markdown files into the FRIDAY workspace "
                        "folder 'notes'. The location is fixed; existing files are never overwritten.",
            schema={"type": "object", "properties": {"id": {"type": "integer", "minimum": 1}}},
            tier=RiskTier.T1,
        )
        def note_export(ctx: ToolContext, id: int | None = None) -> str:
            rows = [n_store.get(id)] if id else n_store.list(500)
            rows = [n for n in rows if n is not None]
            if not rows:
                raise ToolError("nothing to export")
            out_dir = Path(workspace) / "notes"
            out_dir.mkdir(parents=True, exist_ok=True)
            if not os.path.realpath(out_dir).casefold().startswith(os.path.realpath(workspace).casefold() + os.sep):
                raise ToolError("the notes export folder resolves outside the workspace; refusing to write there")
            written = []
            for n in rows:
                slug = re.sub(r"[^a-z0-9]+", "-", n.title.lower()).strip("-")[:40] or "note"
                path = out_dir / f"{n.id:04d}-{slug}.md"
                stamp = datetime.fromtimestamp(n.updated_at, tz).strftime("%Y-%m-%d %H:%M")
                head = f"# {n.title}\n\n" + (f"Tags: {', '.join(n.tags)}  \n" if n.tags else "") + f"Updated: {stamp}\n\n"
                try:
                    with open(path, "x", encoding="utf-8", newline="\n") as fh:
                        fh.write(head + n.body.rstrip("\n") + "\n")
                    written.append(path.name)
                except FileExistsError:
                    continue
            return f"Exported {len(written)} note(s) to {out_dir}" + ("" if written else " (already exported)")

    # ------------------------------------------------------------------ reminders / alarms
    def rem_line(r: Any) -> str:
        rep = f", repeats {r.repeat}" if r.repeat != "none" else ""
        return f"#{r.id} [{r.status}] {fmt_when(r.due_at, tz)}{rep}: {r.message}"

    if reminders:
        @registry.tool(
            name="reminder_set",
            description="Set a reminder or alarm: FRIDAY notifies the user at that time, even after a restart. Give either "
                        "'at' (a date/time) or 'in_minutes'. Use repeat for recurring alarms.",
            schema={"type": "object", "properties": {
                "message": {"type": "string", "minLength": 1, "maxLength": 300},
                "at": {"type": "string", "maxLength": 40, "description": DUE_DESC},
                "in_minutes": {"type": "integer", "minimum": 1, "maximum": 525600},
                "repeat": {"type": "string", "enum": list(REPEATS)},
                "task_id": {"type": "integer", "minimum": 1},
            }, "required": ["message"]},
            tier=RiskTier.T1, rate_limit_per_min=20,
        )
        def reminder_set(ctx: ToolContext, message: str, at: str | None = None, in_minutes: int | None = None,
                         repeat: str = "none", task_id: int | None = None) -> str:
            if (at is None) == (in_minutes is None):
                raise ToolError("give exactly one of 'at' or 'in_minutes'")
            now = clock()
            due = when(at) if at else now + in_minutes * 60  # type: ignore[operator]
            if due < now - 60:
                raise ToolError(f"{fmt_when(due, tz)} is in the past (now is {fmt_when(now, tz)})")
            limit = cfg.tools.max_pending_reminders
            if r_store.pending_count() >= limit:
                raise ToolError(f"too many pending reminders (limit {limit}); cancel some first")
            if task_id is not None and t_store.get(task_id) is None:
                raise ToolError(f"no task #{task_id}")
            rid = r_store.add(message, max(due, now), repeat, task_id, tainted=ctx.tainted)
            if scheduler:
                scheduler.poke()
            rep = f", repeating {repeat}" if repeat != "none" else ""
            return f"Reminder #{rid} set for {fmt_when(due, tz)}{rep}."

        @registry.tool(
            name="reminder_list",
            description="List pending reminders/alarms (soonest first) and the most recent ones that fired.",
            schema={"type": "object", "properties": {}},
            tier=RiskTier.T0, output_trust=Trust.RECALLED,
        )
        def reminder_list(ctx: ToolContext) -> ToolOutput:
            pend = r_store.pending()
            done = r_store.recent_fired(5)
            lines = [rem_line(r) for r in pend] or ["No pending reminders."]
            if done:
                lines += ["Recently fired:"] + [rem_line(r) for r in done]
            return ToolOutput("\n".join(lines), source="reminders", untrusted=_data_flag([*pend, *done]))

        @registry.tool(
            name="reminder_cancel",
            description="Cancel a pending reminder/alarm by id.",
            schema={"type": "object", "properties": {"id": {"type": "integer", "minimum": 1}}, "required": ["id"]},
            tier=RiskTier.T1,
        )
        def reminder_cancel(ctx: ToolContext, id: int) -> str:
            ok = r_store.cancel(id)
            if ok and scheduler:
                scheduler.poke()
            return f"Cancelled reminder #{id}." if ok else f"No pending reminder #{id}."

        @registry.tool(
            name="reminder_snooze",
            description="Push a reminder (pending or just fired) to fire again after N minutes from now.",
            schema={"type": "object", "properties": {
                "id": {"type": "integer", "minimum": 1},
                "minutes": {"type": "integer", "minimum": 1, "maximum": 10080},
            }, "required": ["id", "minutes"]},
            tier=RiskTier.T1,
        )
        def reminder_snooze(ctx: ToolContext, id: int, minutes: int) -> str:
            due = clock() + minutes * 60
            if not r_store.snooze(id, due):
                raise ToolError(f"no reminder #{id} to snooze")
            if scheduler:
                scheduler.poke()
            return f"Reminder #{id} will fire at {fmt_when(due, tz)}."

    return {"tasks": t_store, "notes": n_store, "reminders": r_store}
