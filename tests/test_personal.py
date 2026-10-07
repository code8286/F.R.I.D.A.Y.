# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

import time
import unittest
from datetime import datetime, timedelta, timezone

from friday.brain.context_builder import _tz
from friday.core.audit import AuditLog
from friday.core.bus import EventBus
from friday.core.db import Database
from friday.core.errors import ToolError
from friday.personal.scheduler import Scheduler
from friday.personal.store import NoteStore, ReminderStore, TaskStore, next_occurrence, parse_when
from tests.helpers import AsyncTempDirCase, TempDirCase, calls, make_tools_core, run_tool, say, tool_results, use

IST = _tz("Asia/Kolkata")          # falls back to a fixed +05:30 when the tz database is missing (Windows)
UTC = timezone.utc


class TimeHelperTests(unittest.TestCase):
    def test_parse_when_variants(self):
        now = time.time()
        a = parse_when("2026-10-07T18:30", IST, now)
        self.assertEqual(datetime.fromtimestamp(a, IST).strftime("%H:%M"), "18:30")
        self.assertEqual(parse_when("2026-10-07T18:30+00:00", IST, now), datetime(2026, 10, 7, 18, 30, tzinfo=UTC).timestamp())
        self.assertEqual(parse_when("2026-10-07T13:00:00Z", IST, now), datetime(2026, 10, 7, 13, 0, tzinfo=UTC).timestamp())
        self.assertEqual(datetime.fromtimestamp(parse_when("2026-10-07", IST, now), IST).strftime("%H:%M"), "09:00")
        for bad in ("tomorrow", "", "2026-13-40T99:99"):
            with self.assertRaises(ToolError):
                parse_when(bad, IST, now)

    def test_next_occurrence_skips_the_past_and_weekends(self):
        fri = datetime(2026, 10, 9, 9, 0, tzinfo=IST)          # a Friday
        self.assertEqual(datetime.fromtimestamp(next_occurrence(fri.timestamp(), "weekdays", IST, fri.timestamp()), IST).weekday(), 0)
        daily = next_occurrence(fri.timestamp(), "daily", IST, fri.timestamp() + 10 * 86400 + 5)
        self.assertEqual(datetime.fromtimestamp(daily, IST).date(), (fri + timedelta(days=11)).date())
        self.assertIsNone(next_occurrence(fri.timestamp(), "none", IST, 0))


class StoreTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.db = Database(self.tmp / "t.db").open()
        self.addCleanup(self.db.close)
        self.now = 1_800_000_000.0

    def test_tasks_lifecycle_and_ordering(self):
        s = TaskStore(self.db, lambda: self.now)
        a = s.add("later", priority=3, due_at=self.now + 1000)
        b = s.add("sooner", due_at=self.now + 10)
        c = s.add("undated")
        self.assertEqual([t.id for t in s.list()], [b, a, c])
        self.assertTrue(s.update(b, status="done"))
        self.assertEqual([t.id for t in s.list("done")], [b])
        self.assertIsNotNone(s.get(b).completed_at)
        s.update(b, status="open")
        self.assertIsNone(s.get(b).completed_at)
        self.assertEqual(s.counts(), (3, 0))
        self.now += 100
        self.assertEqual(s.counts(), (3, 1))
        self.assertTrue(s.delete(a))
        self.assertFalse(s.delete(a))

    def test_notes_search_escapes_wildcards(self):
        n = NoteStore(self.db, lambda: self.now)
        n.add("Plan", "buy 100% cotton", ["Home Stuff", "home stuff"])
        n.add("Other", "nothing here")
        self.assertEqual([x.title for x in n.search("100%")], ["Plan"])
        self.assertEqual(n.search("%"), [n.get(1)])            # a literal percent, not "match everything"
        self.assertEqual(n.get(1).tags, ("home-stuff",))
        n.update(1, append="more")
        self.assertTrue(n.get(1).body.endswith("\nmore"))
        self.assertTrue(n.delete(1))

    def test_reminder_states(self):
        r = ReminderStore(self.db, lambda: self.now)
        rid = r.add("x", self.now + 5)
        self.assertEqual(r.due(self.now), [])
        self.assertEqual(len(r.due(self.now + 5)), 1)
        r.mark_fired(rid, self.now + 5, None)
        self.assertEqual(r.get(rid).status, "fired")
        self.assertTrue(r.snooze(rid, self.now + 60))
        self.assertEqual(r.get(rid).status, "pending")
        self.assertTrue(r.cancel(rid))
        self.assertFalse(r.cancel(rid))


class SchedulerTests(AsyncTempDirCase):
    async def test_fires_once_repeats_and_flags_late(self):
        db = Database(self.tmp / "s.db").open()
        self.addCleanup(db.close)
        bus = EventBus()
        bus.bind_loop()
        audit = AuditLog(db)
        clock = [1_800_000_000.0]
        store = ReminderStore(db, lambda: clock[0])
        sched = Scheduler(store, bus, audit, IST, lambda: clock[0])
        seen = []
        bus.on("reminder.due", lambda ev: seen.append(ev.payload))
        once = store.add("once", clock[0] + 10)
        rep = store.add("daily", clock[0] + 20, "daily")
        self.assertEqual(sched.fire_due(), 0)
        clock[0] += 30
        self.assertEqual(sched.fire_due(), 2)
        self.assertEqual(sched.fire_due(), 0)                    # nothing fires twice
        self.assertEqual(store.get(once).status, "fired")
        self.assertEqual(store.get(rep).status, "pending")
        self.assertGreater(store.get(rep).due_at, clock[0])
        self.assertFalse(any(p["late"] for p in seen))
        clock[0] += 3 * 86400                                    # FRIDAY was "off" for three days
        self.assertEqual(sched.fire_due(), 1)
        self.assertTrue(seen[-1]["late"])
        self.assertEqual(len([e for e in audit.tail(20) if e.event == "reminder.fired"]), 3)

    async def test_background_task_fires_and_wakes_on_new_reminder(self):
        import asyncio

        db = Database(self.tmp / "s2.db").open()
        self.addCleanup(db.close)
        bus = EventBus()
        bus.bind_loop()
        store = ReminderStore(db)
        sched = Scheduler(store, bus, AuditLog(db), IST)
        sub = bus.subscribe("reminder.due")
        sched.start()
        await asyncio.sleep(0.05)                                # scheduler is now asleep for up to 30 s
        store.add("soon", time.time() + 0.3)
        sched.poke()                                             # ...and is woken to recompute its sleep
        ev = await sub.get(timeout=3)
        self.assertEqual(ev.payload["message"], "soon")
        await sched.stop()
        sub.close()


class PersonalToolTests(AsyncTempDirCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.rig = await make_tools_core(self.tmp, [])
        self.addAsyncCleanup(self.rig.core.stop)

    async def test_task_and_note_flow_through_the_loop(self):
        r = await run_tool(self.rig, "task_add", {"title": "Buy milk", "priority": 1, "due": (datetime.now() + timedelta(days=400)).strftime("%Y-%m-%dT10:00")}, approve=None)
        self.assertIn("Added task #1", r.content)
        r = await run_tool(self.rig, "task_list", {}, approve=None)
        self.assertIn("Buy milk", r.content)
        self.assertIn("<recalled_data", r.content)              # stored text comes back as data
        self.assertNotIn("<untrusted_data", r.content)
        self.assertFalse(self.rig.core.sessions.main().is_tainted())   # reading your own tasks doesn't taint
        r = await run_tool(self.rig, "task_update", {"id": 1, "status": "done"}, approve=None)
        self.assertIn("Updated", r.content)
        r = await run_tool(self.rig, "task_update", {"id": 99, "status": "done"}, approve=None)
        self.assertTrue(r.is_error)
        r = await run_tool(self.rig, "note_add", {"title": "Idea", "body": "rocket gimbal", "tags": ["tvc"]}, approve=None)
        self.assertIn("note #1", r.content)
        r = await run_tool(self.rig, "note_search", {"query": "gimbal"}, approve=None)
        self.assertIn("Idea", r.content)

    async def test_deletes_and_body_replacement_need_approval(self):
        await run_tool(self.rig, "task_add", {"title": "t"}, approve=None)
        await run_tool(self.rig, "note_add", {"title": "n", "body": "b"}, approve=None)
        seen = self.rig.auto_respond(False)
        for name, args in (("task_delete", {"id": 1}), ("note_delete", {"id": 1}), ("note_update", {"id": 1, "body": "new"})):
            self.rig.provider.script.extend([calls(use(name, args)), say("ok")])
            await self.rig.core.submit(name)
        self.assertEqual(len(seen), 3)
        self.assertIsNotNone(self.rig.core.personal["tasks"].get(1))        # denied: nothing was deleted
        self.assertEqual(self.rig.core.personal["notes"].get(1).body, "b")

    async def test_append_to_note_is_t1_but_tainted_turn_needs_approval(self):
        await run_tool(self.rig, "note_add", {"title": "n", "body": "b"}, approve=None)
        r = await run_tool(self.rig, "note_update", {"id": 1, "append": "more"}, approve=None)
        self.assertIn("Updated", r.content)
        self.rig.provider.script.extend([calls(use("fs_list", {"path": "~"})), say("x")])
        await self.rig.core.submit("poison the session")         # fs_list output is untrusted -> session tainted
        self.assertTrue(self.rig.core.sessions.main().is_tainted())
        seen = self.rig.auto_respond(False)
        r = await run_tool(self.rig, "note_add", {"title": "evil", "body": "x"}, approve=False)
        self.assertTrue(seen and r.is_error)
        self.assertIn("NOT APPROVED", r.content)
        self.assertEqual(len(self.rig.core.personal["notes"].list()), 1)

    async def test_reminder_set_validates_and_fires_into_bus_not_model(self):
        r = await run_tool(self.rig, "reminder_set", {"message": "x"}, approve=None)
        self.assertTrue(r.is_error)                                      # neither 'at' nor 'in_minutes'
        r = await run_tool(self.rig, "reminder_set", {"message": "x", "at": "2001-01-01T00:00", "in_minutes": 5}, approve=None)
        self.assertTrue(r.is_error)                                      # both
        r = await run_tool(self.rig, "reminder_set", {"message": "x", "at": "2001-01-01T00:00"}, approve=None)
        self.assertIn("in the past", r.content)
        r = await run_tool(self.rig, "reminder_set", {"message": "stand up", "in_minutes": 1}, approve=None)
        self.assertIn("Reminder #1", r.content)
        rem = self.rig.core.scheduler.store
        seen = []
        self.rig.core.bus.on("reminder.due", lambda ev: seen.append(ev.payload))
        rem.snooze(1, time.time() - 1)
        self.assertEqual(self.rig.core.scheduler.fire_due(), 1)
        self.assertEqual(seen[0]["message"], "stand up")
        calls_before = len(self.rig.provider.calls)
        self.assertEqual(len(self.rig.provider.calls), calls_before)     # firing never calls the model
        r = await run_tool(self.rig, "reminder_list", {}, approve=None)
        self.assertIn("Recently fired", r.content)

    async def test_pending_reminder_cap_and_cancel(self):
        self.rig.core.cfg.tools.max_pending_reminders = 2
        for i in range(2):
            r = await run_tool(self.rig, "reminder_set", {"message": f"m{i}", "in_minutes": 5}, approve=None)
            self.assertFalse(r.is_error)
        r = await run_tool(self.rig, "reminder_set", {"message": "m3", "in_minutes": 5}, approve=None)
        self.assertIn("too many", r.content)
        r = await run_tool(self.rig, "reminder_cancel", {"id": 1}, approve=None)
        self.assertIn("Cancelled", r.content)
        r = await run_tool(self.rig, "reminder_set", {"message": "m3", "in_minutes": 5}, approve=None)
        self.assertFalse(r.is_error)

    async def test_note_export_writes_markdown_to_fixed_folder_without_overwriting(self):
        await run_tool(self.rig, "note_add", {"title": "My Idea!", "body": "body text", "tags": ["a"]}, approve=None)
        r = await run_tool(self.rig, "note_export", {}, approve=None)
        f = self.tmp / "ws" / "notes" / "0001-my-idea.md"
        self.assertTrue(f.exists(), r.content)
        self.assertIn("body text", f.read_text(encoding="utf-8"))
        f.write_text("user edit", encoding="utf-8")
        await run_tool(self.rig, "note_export", {}, approve=None)
        self.assertEqual(f.read_text(encoding="utf-8"), "user edit")

    async def test_live_context_shows_open_task_count(self):
        await run_tool(self.rig, "task_add", {"title": "a"}, approve=None)
        self.rig.provider.script.append(say("hi"))
        await self.rig.core.submit("hello")
        self.assertIn("Open tasks: 1 open", self.rig.provider.calls[-1]["system"])

    async def test_tool_groups_can_be_switched_off(self):
        rig = await make_tools_core(self.tmp / "off", [], mutate=lambda c: (setattr(c.tools, "fs", False), setattr(c.tools, "shell", False),
                                                                           setattr(c.tools, "web", False), setattr(c.tools, "reminders", False),
                                                                           setattr(c.tools, "notes", False)))
        self.addAsyncCleanup(rig.core.stop)
        names = rig.core.registry.names()
        self.assertIn("task_add", names)
        for gone in ("fs_read", "shell_run", "web_fetch", "reminder_set", "note_add"):
            self.assertNotIn(gone, names)
        self.assertIsNone(rig.core.scheduler)
        self.assertTrue(tool_results(rig.core) == [])


class CliShowTests(TempDirCase):
    def test_show_commands_are_read_only_and_print_rows(self):
        import contextlib
        import io

        from friday import __main__ as cli

        db = Database(self.tmp / "friday.db").open()
        TaskStore(db).add("Buy milk")
        NoteStore(db).add("Idea", "x")
        ReminderStore(db).add("Stand up", time.time() + 3600)
        db.close()
        cfgfile = self.tmp / "config.toml"
        cfgfile.write_text(f'data_dir = {str(self.tmp)!r}\n', encoding="utf-8")
        for what, needle in (("tasks", "Buy milk"), ("notes", "Idea"), ("reminders", "Stand up"), ("trash", "")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["--config", str(cfgfile), "show", what])
            self.assertEqual(rc, 0)
            self.assertIn(needle, out.getvalue())


if __name__ == "__main__":
    unittest.main()
