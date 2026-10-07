# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""In-process fake of `friday-core` for `--mock` (brief section 4.6).

It speaks the same envelope the real core will speak over the UI WebSocket:
  core -> UI   {type: <topic>, op: snapshot|add|update|remove|move, ...}, {type: "action.result", id, ok, error?},
               {type: "audio.spectrum" | "tts.spectrum", bands, rms, clap}, {type: "activation.state", state},
               {type: "media.now_playing", ...}, {type: "event", name, ...}
  UI -> core   {type: "subscribe" | "unsubscribe", topics}, {type: "action", id, name, args}

Everything a user does goes through `send()` as an action, and the mock decides (including asking for a
confirmation for T2 actions), exactly as the real policy engine will. Data is demo data generated relative to
"now", so countdowns are live whatever the time of day.
"""

from __future__ import annotations

import math
import random
import time
import uuid
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .. import timeutil as tu

LIST_TOPICS = ["calendar.events", "reminders", "todos", "alarms", "notifications", "agent.tasks", "routines", "commands"]
STATE_CYCLE = ["listening", "thinking", "speaking", "idle", "confirm"]

PLAYLIST = [
    {"track_id": "t1", "title": "Interstellar Main Theme", "artist": "Hans Zimmer", "album": "Interstellar", "duration": 275},
    {"track_id": "t2", "title": "Cornfield Chase", "artist": "Hans Zimmer", "album": "Interstellar", "duration": 126},
    {"track_id": "t3", "title": "Time", "artist": "Hans Zimmer", "album": "Inception", "duration": 275},
    {"track_id": "t4", "title": "Experience", "artist": "Ludovico Einaudi", "album": "In a Time Lapse", "duration": 315},
    {"track_id": "t5", "title": "Nuvole Bianche", "artist": "Ludovico Einaudi", "album": "Una Mattina", "duration": 357},
]


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _public(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


class MockCore(QObject):
    message = Signal(object)

    def __init__(self, *, script: bool = True, cycle: bool = True, parent: Any = None):
        super().__init__(parent)
        self.online = True
        self.client = False
        self.subs: set[str] = set()
        self.t0 = time.time()
        self.cycle = cycle
        self.state = "listening"
        self._cycle_i = 0
        self._ptt = False
        self._fail_next = False
        self._clap_at = time.time() + 7
        self._pending: dict[str, Callable[[bool], None]] = {}
        self._mic_external = False      # --mock-mic feeds the spectrum instead
        self.data: dict[str, list[dict]] = {t: [] for t in LIST_TOPICS}
        self.media: dict = {}
        self._seed()

        self._tick = QTimer(self, interval=1000, timeout=self._on_tick)
        self._spec = QTimer(self, interval=33, timeout=self._on_spectrum)
        self._cyc = QTimer(self, interval=4000, timeout=self._on_cycle)
        self._steps = QTimer(self, interval=2600, timeout=self._advance_tasks)
        self._tick.start()
        self._cyc.start()
        self._steps.start()
        self._script: list[tuple[float, Callable[[], None]]] = []
        if script:
            self._build_script()
            self._scr = QTimer(self, interval=250, timeout=self._on_script)
            self._scr.start()

    # ================================================================== seed data
    def _seed(self) -> None:
        now = self.t0
        d = tu.local(now)

        def day(add: int, h: int, m: int) -> float:
            base = d.replace(hour=h, minute=m, second=0, microsecond=0)
            return base.timestamp() + add * 86400

        standup = now + 17 * 60 + 43
        self.data["calendar.events"] = [
            {"id": "ev_standup", "title": "Standup", "calendar": "Atlas team", "start": standup, "end": standup + 900, "location": "Meet · atlas-daily", "notes": "Thrust-vector loop tuning, bench results."},
            {"id": "ev_review", "title": "GRN figure review", "calendar": "Lab", "start": now + 3 * 3600 + 900, "end": now + 3 * 3600 + 900 + 2700, "location": "Lab 3, EEE block", "notes": "Bring the hPSC plots."},
            {"id": "ev_bench", "title": "TVC bench test", "calendar": "Atlas team", "start": day(1, 14, 0), "end": day(1, 16, 0), "location": "Workshop", "notes": "Servo spares needed."},
            {"id": "ev_labsync", "title": "Lab sync", "calendar": "Lab", "start": day(3, 11, 0), "end": day(3, 12, 0), "location": "Online", "notes": ""},
            {"id": "ev_gravbox", "title": "GravBox web release", "calendar": "Personal", "start": day(6, 18, 0), "end": day(6, 19, 0), "location": "", "notes": "Tag v0.9, publish Pages."},
            {"id": "ev_quiz", "title": "Signals quiz", "calendar": "VIT", "start": day(9, 9, 30), "end": day(9, 10, 30), "location": "SJT 302", "notes": ""},
            {"id": "ev_othisis", "title": "Othisis intro call", "calendar": "Personal", "start": day(-3, 16, 0), "end": day(-3, 16, 30), "location": "Phone", "notes": ""},
            {"id": "ev_f1", "title": "Race weekend · quali", "calendar": "Personal", "start": day(12, 18, 30), "end": day(12, 19, 30), "location": "", "notes": ""},
            {"id": "ev_lab2", "title": "Imaging slot", "calendar": "Lab", "start": day(15, 10, 0), "end": day(15, 12, 0), "location": "Confocal room", "notes": ""},
        ]
        self.data["reminders"] = [
            {"id": "rm_othisis", "text": "Reply to Othisis", "at": now - 35 * 60, "done": False, "due": True, "untrusted": False},
            {"id": "rm_lab", "text": "Call lab", "at": now + 4 * 3600 + 48 * 60, "done": False, "due": False, "untrusted": False},
            {"id": "rm_fee", "text": "Pay hostel fee", "at": now + 6 * 3600 + 10 * 60, "done": False, "due": False, "untrusted": False},
            {"id": "rm_backup", "text": "Back up Atlas flight logs", "at": now + 8 * 3600, "done": False, "due": False, "untrusted": False},
            {"id": "rm_books", "text": "Renew library books", "at": day(1, 10, 0), "done": False, "due": False, "untrusted": False},
            {"id": "rm_report", "text": "Submit lab report", "at": day(3, 17, 0), "done": False, "due": False, "untrusted": False},
        ]
        self.data["todos"] = [
            {"id": "td_grn", "text": "Finish GRN figure draft", "done": False, "priority": 2, "due": now + 6 * 3600, "order": 0, "done_at": 0, "untrusted": False},
            {"id": "td_pr", "text": "Review GravBox PR #42", "done": False, "priority": 1, "due": 0, "order": 1, "done_at": 0, "untrusted": False},
            {"id": "td_servo", "text": "Order spare TVC servos", "done": False, "priority": 3, "due": day(2, 18, 0), "order": 2, "done_at": 0, "untrusted": False},
            {"id": "td_mail", "text": "Email lab about imaging slot", "done": True, "priority": 2, "due": 0, "order": 3, "done_at": now - 3600, "untrusted": False},
        ]
        self.data["alarms"] = [
            {"id": "al_wake", "hour": 7, "minute": 0, "label": "Wake up", "days": [0, 1, 2, 3, 4], "enabled": True, "ringing": False},
            {"id": "al_weekend", "hour": 9, "minute": 0, "label": "Weekend", "days": [5, 6], "enabled": False, "ringing": False},
            {"id": "al_lab", "hour": 13, "minute": 45, "label": "Lab prep", "days": [2], "enabled": False, "ringing": False},
        ]
        self.data["notifications"] = [
            {"id": "nt_tg", "kind": "telegram", "title": "Telegram · Rohan", "text": "Lab moved to 15:45 today, bring the GRN plots.", "ts": now - 6 * 60, "read": False, "untrusted": True},
            {"id": "nt_brief", "kind": "task", "title": "Morning brief ready", "text": "3 meetings today, 2 PRs waiting for review, 1 overdue reminder.", "ts": now - 2 * 3600 - 40 * 60, "read": False, "untrusted": False},
        ]
        self.data["agent.tasks"] = [
            {"id": "tk_sum", "title": "Summarise unread email", "source": "agent", "status": "running", "meta": "~40s", "order": 0, "progress": -1, "archived": False, "finished": 0,
             "steps": [{"text": "fetch inbox · 12 unread", "state": "done"}, {"text": "cluster by thread", "state": "running"}],
             "_plan": ["rank by urgency", "write the summary"], "detail": "Asked by you at 10:20 · reads mail as untrusted data"},
            {"id": "tk_push", "title": "Push GravBox Web build", "source": "agent", "status": "awaiting", "meta": "T2", "order": 1, "progress": -1, "archived": False, "finished": 0,
             "steps": [{"text": "build web bundle", "state": "done"}, {"text": "git push origin gh-pages · needs approval", "state": "waiting"}],
             "_plan": ["git push origin gh-pages", "verify Pages deploy"], "detail": "shell_run · git push origin gh-pages"},
            {"id": "tk_draft", "title": "Draft Othisis follow-up email", "source": "you", "status": "queued", "meta": "next", "order": 2, "progress": -1, "archived": False, "finished": 0,
             "steps": [], "_plan": ["read the last thread", "draft a reply", "save to drafts"], "detail": "From your voice note at 09:58"},
            {"id": "tk_evening", "title": "Evening brief", "source": "routine", "status": "queued", "meta": "19:00", "order": 3, "progress": -1, "archived": False, "finished": 0,
             "steps": [], "_plan": [], "detail": "Routine · daily 19:00"},
            {"id": "tk_morning", "title": "Morning brief", "source": "routine", "status": "done", "meta": "08:00", "order": 9, "progress": 1, "archived": True, "finished": now - 9600,
             "steps": [{"text": "calendar · 3 events", "state": "done"}, {"text": "GitHub · 2 PRs", "state": "done"}, {"text": "spoken summary", "state": "done"}], "_plan": [], "detail": "Routine · daily 08:00"},
        ]
        self.data["routines"] = [
            {"id": "rt_night", "title": "Night wind-down · 23:00", "enabled": True},
            {"id": "rt_digest", "title": "Weekly GitHub digest · Sun", "enabled": False},
        ]
        self.data["commands"] = [
            self._command("cm_brief", "brief me on calendar + GitHub", "daily 08:00", last="ok 2 h ago"),
            self._command("cm_wake", "read today's reminders", "on wake", last="ok at 08:05"),
            self._command("cm_inbox", "check lab inbox", "every 2h", last="ok 1 h ago"),
            self._command("cm_sync", "sync GravBox issues", "weekdays 18:30", last="ok yesterday"),
            self._command("cm_atlas", "log Atlas test notes", "on clap", last="paused 3 d ago", paused=True),
        ]
        inbox = self._find("commands", "cm_inbox")
        if inbox:   # the demo fires this one ~50 s after launch
            inbox["next"] = now + 52
            inbox["prev"] = inbox["next"] - inbox["period"]
        tg = self._command("x", "x", "daily 08:00")
        del tg
        self.media = dict(PLAYLIST[0], position=102.0, playing=True, session=True, volume=0.62, shuffle=False, repeat="off", source="Spotify (mock media session)")

    def _command(self, cid: str, text: str, trigger: str, *, last: str = "never", paused: bool = False) -> dict:
        trig = tu.parse_trigger(trigger, self.t0)
        nxt = float(trig.get("next") or 0)
        period = float(trig.get("period") or 0)
        return {"id": cid, "text": text, "trigger": trigger, "chip": trig.get("chip", trigger), "kind": trig.get("kind", "event"),
                "next": nxt, "prev": (nxt - period) if period else 0, "period": period, "last": last, "paused": paused, "untrusted": False,
                "_trig": trig}

    # ================================================================== transport
    def connect_client(self) -> bool:
        if not self.online:
            return False
        self.client = True
        return True

    def send(self, msg: dict) -> None:
        if not (self.online and self.client):
            return
        typ = msg.get("type")
        if typ == "subscribe":
            for t in msg.get("topics", []):
                self.subs.add(t)
                if t in LIST_TOPICS:
                    self._emit({"type": t, "op": "snapshot", "items": [_public(i) for i in self.data[t]]})
                elif t == "media.now_playing":
                    self._emit_media()
                elif t == "activation.state":
                    self._emit({"type": "activation.state", "state": self.state})
            self._spec_update()
        elif typ == "unsubscribe":
            for t in msg.get("topics", []):
                self.subs.discard(t)
            self._spec_update()
        elif typ == "action":
            QTimer.singleShot(random.randint(60, 160), lambda m=dict(msg): self._handle_action(m))

    def _emit(self, msg: dict) -> None:
        if self.online and self.client:
            self.message.emit(msg)

    def _spec_update(self) -> None:
        want = ("audio.spectrum" in self.subs or "tts.spectrum" in self.subs) and not self._mic_external
        if want and not self._spec.isActive():
            self._spec.start()
        elif not want and self._spec.isActive():
            self._spec.stop()

    def set_external_mic(self, on: bool) -> None:
        self._mic_external = on
        self._spec_update()

    # ------------------------------------------------------------------ list helpers
    def _find(self, topic: str, item_id: str) -> dict | None:
        return next((i for i in self.data[topic] if i["id"] == item_id), None)

    def _add(self, topic: str, item: dict, index: int | None = None) -> None:
        lst = self.data[topic]
        index = len(lst) if index is None else max(0, min(index, len(lst)))
        lst.insert(index, item)
        if topic in self.subs:
            self._emit({"type": topic, "op": "add", "item": _public(item), "index": index})

    def _update(self, topic: str, item_id: str, **fields: Any) -> dict | None:
        it = self._find(topic, item_id)
        if it is None:
            return None
        it.update(fields)
        if topic in self.subs:
            self._emit({"type": topic, "op": "update", "item": _public(it)})
        return it

    def _remove(self, topic: str, item_id: str) -> None:
        lst = self.data[topic]
        for i, it in enumerate(lst):
            if it["id"] == item_id:
                del lst[i]
                if topic in self.subs:
                    self._emit({"type": topic, "op": "remove", "id": item_id})
                return

    def _event(self, name: str, **payload: Any) -> None:
        self._emit({"type": "event", "name": name, **payload})

    def _set_state(self, st: str) -> None:
        if st != self.state:
            self.state = st
            self._emit({"type": "activation.state", "state": st})

    def _emit_media(self) -> None:
        self._emit({"type": "media.now_playing", "op": "set", **self.media})

    # ================================================================== actions
    def _handle_action(self, msg: dict) -> None:
        aid, name, args = msg.get("id"), msg.get("name", ""), dict(msg.get("args") or {})

        def reply(ok: bool = True, error: str = "", **extra: Any) -> None:
            out = {"type": "action.result", "id": aid, "ok": ok, **extra}
            if error:
                out["error"] = error
            self._emit(out)

        if self._fail_next and not name.startswith("dev."):
            self._fail_next = False
            reply(False, "demo: the core refused this action")
            return
        fn = getattr(self, "_a_" + name.replace(".", "_"), None)
        if fn is None:
            reply(False, f"unknown action {name}")
            return
        try:
            res = fn(args)
        except Exception as exc:  # noqa: BLE001 - a demo bug must never take the UI down
            reply(False, f"{type(exc).__name__}: {exc}")
            return
        if isinstance(res, dict) and res.get("confirm"):
            reply(True, pending=True, confirm_id=res["confirm"])
        elif isinstance(res, str):
            reply(False, res)
        else:
            reply(True)

    def _confirm(self, title: str, text: str, tier: int, on_decide: Callable[[bool], None], *, tool: str = "") -> dict:
        nid = _id("cf")
        self._pending[nid] = on_decide
        self._add("notifications", {"id": nid, "kind": "confirm", "title": f"Confirm · T{tier}", "text": text, "action": title, "tool": tool,
                                    "tier": tier, "ts": time.time(), "read": False, "untrusted": False, "resolved": ""}, 0)
        self._event("confirm.request", id=nid, tier=tier, action=title)
        return {"confirm": nid}

    # --- confirmations
    def _a_confirm_respond(self, a: dict) -> Any:
        nid, approve = a.get("id"), bool(a.get("approve"))
        cb = self._pending.pop(nid, None)
        if cb is None:
            return "this request already expired or was answered"
        self._update("notifications", nid, resolved="approved" if approve else "denied", read=True)
        QTimer.singleShot(1600, lambda: self._remove("notifications", nid))
        cb(approve)
        if not self._pending and self.state == "confirm":
            self._set_state("idle")
        return None

    # --- todos
    def _a_todo_add(self, a: dict) -> Any:
        text = str(a.get("text", "")).strip()
        if not text:
            return "empty to-do"
        open_items = [t for t in self.data["todos"] if not t["done"]]
        for t in open_items:
            self._update("todos", t["id"], order=t["order"] + 1)
        self._add("todos", {"id": _id("td"), "text": text[:200], "done": False, "priority": int(a.get("priority", 2)), "due": float(a.get("due", 0) or 0),
                            "order": 0, "done_at": 0, "untrusted": False}, 0)
        return None

    def _a_todo_toggle(self, a: dict) -> Any:
        t = self._find("todos", a.get("id", ""))
        if not t:
            return "no such to-do"
        done = not t["done"] if "done" not in a else bool(a["done"])
        self._update("todos", t["id"], done=done, done_at=time.time() if done else 0)
        return None

    def _a_todo_reorder(self, a: dict) -> Any:
        open_items = sorted([t for t in self.data["todos"] if not t["done"]], key=lambda t: t["order"])
        it = next((t for t in open_items if t["id"] == a.get("id")), None)
        if it is None:
            return "no such to-do"
        open_items.remove(it)
        open_items.insert(max(0, min(int(a.get("index", 0)), len(open_items))), it)
        for i, t in enumerate(open_items):
            if t["order"] != i:
                self._update("todos", t["id"], order=i)
        return None

    def _a_todo_update(self, a: dict) -> Any:
        fields = {k: a[k] for k in ("text", "priority", "due") if k in a}
        return None if self._update("todos", a.get("id", ""), **fields) else "no such to-do"

    def _a_todo_delete(self, a: dict) -> Any:
        t = self._find("todos", a.get("id", ""))
        if not t:
            return "no such to-do"
        self._trash = dict(t)
        self._remove("todos", t["id"])
        return None

    def _a_todo_undo_delete(self, a: dict) -> Any:
        t = getattr(self, "_trash", None)
        if not t or t["id"] != a.get("id"):
            return "nothing to undo"
        self._trash = None
        self._add("todos", t)
        return None

    # --- reminders
    def _a_reminder_add(self, a: dict) -> Any:
        text = str(a.get("text", "")).strip()
        if not text:
            return "empty reminder"
        self._add("reminders", {"id": _id("rm"), "text": text[:200], "at": float(a.get("at") or time.time() + 600), "done": False, "due": False, "untrusted": False})
        return None

    def _a_reminder_snooze(self, a: dict) -> Any:
        at = tu.snooze_target(str(a.get("choice", "15m")))
        return None if self._update("reminders", a.get("id", ""), at=at, due=False) else "no such reminder"

    def _a_reminder_done(self, a: dict) -> Any:
        return None if self._update("reminders", a.get("id", ""), done=True, due=False) else "no such reminder"

    def _a_reminder_delete(self, a: dict) -> Any:
        self._remove("reminders", a.get("id", ""))
        return None

    # --- alarms
    def _a_alarm_add(self, a: dict) -> Any:
        self._add("alarms", {"id": _id("al"), "hour": int(a.get("hour", 7)) % 24, "minute": int(a.get("minute", 0)) % 60, "label": str(a.get("label") or "Alarm")[:60],
                             "days": [int(d) for d in a.get("days", [])], "enabled": True, "ringing": False})
        return None

    def _a_alarm_toggle(self, a: dict) -> Any:
        al = self._find("alarms", a.get("id", ""))
        if not al:
            return "no such alarm"
        self._update("alarms", al["id"], enabled=not al["enabled"] if "enabled" not in a else bool(a["enabled"]))
        return None

    def _a_alarm_update(self, a: dict) -> Any:
        al = self._find("alarms", a.get("id", ""))
        if al:
            al.pop("_next", None)
        fields = {k: a[k] for k in ("hour", "minute", "label", "days") if k in a}
        return None if self._update("alarms", a.get("id", ""), **fields) else "no such alarm"

    def _a_alarm_delete(self, a: dict) -> Any:
        self._remove("alarms", a.get("id", ""))
        return None

    def _a_alarm_stop(self, a: dict) -> Any:
        al = self._find("alarms", a.get("id", ""))
        if not al:
            return "no such alarm"
        self._update("alarms", al["id"], ringing=False, enabled=al["enabled"] if al.get("days") else al.get("_keep", False))
        self._event("alarm.stopped", id=al["id"])
        return None

    def _a_alarm_snooze(self, a: dict) -> Any:
        al = self._find("alarms", a.get("id", ""))
        if not al:
            return "no such alarm"
        self._update("alarms", al["id"], ringing=False)
        self._event("alarm.stopped", id=al["id"])
        al["_snooze_until"] = time.time() + 9 * 60
        return None

    # --- calendar (create/update are T1, delete is T2: a confirmation card comes back)
    def _a_calendar_create(self, a: dict) -> Any:
        title = str(a.get("title", "")).strip()
        if not title:
            return "the event needs a title"
        start = float(a.get("start") or time.time() + 3600)
        self._add("calendar.events", {"id": _id("ev"), "title": title[:120], "calendar": "Personal", "start": start, "end": float(a.get("end") or start + 3600),
                                      "location": str(a.get("location", ""))[:80], "notes": ""})
        return None

    def _a_calendar_update(self, a: dict) -> Any:
        fields = {k: a[k] for k in ("title", "start", "end", "location") if k in a}
        return None if self._update("calendar.events", a.get("id", ""), **fields) else "no such event"

    def _a_calendar_delete(self, a: dict) -> Any:
        ev = self._find("calendar.events", a.get("id", ""))
        if not ev:
            return "no such event"
        when = tu.local(ev["start"]).strftime("%a %d %b %H:%M")
        return self._confirm("Delete calendar event", f"calendar_delete · “{ev['title']}” · {when}", 2,
                             lambda ok, i=ev["id"]: ok and self._remove("calendar.events", i), tool="calendar_delete")

    # --- media
    def _a_media_play_pause(self, a: dict) -> Any:
        if not self.media.get("session"):
            return "Spotify is not running"
        self.media["playing"] = not self.media["playing"]
        self._emit_media()
        return None

    def _track(self, step: int) -> None:
        ids = [p["track_id"] for p in PLAYLIST]
        i = ids.index(self.media["track_id"]) if self.media.get("track_id") in ids else 0
        if self.media.get("shuffle") and step > 0:
            i = random.choice([k for k in range(len(PLAYLIST)) if k != i])
        else:
            i = (i + step) % len(PLAYLIST)
        self.media.update(PLAYLIST[i], position=0.0)
        self._emit_media()

    def _a_media_next(self, a: dict) -> Any:
        self._track(1)

    def _a_media_prev(self, a: dict) -> Any:
        if self.media.get("position", 0) > 3:
            self.media["position"] = 0.0
            self._emit_media()
        else:
            self._track(-1)

    def _a_media_seek(self, a: dict) -> Any:
        self.media["position"] = max(0.0, min(float(a.get("position", 0)), float(self.media.get("duration", 1))))
        self._emit_media()

    def _a_media_volume(self, a: dict) -> Any:
        self.media["volume"] = max(0.0, min(1.0, float(a.get("volume", 0.5))))
        self._emit_media()

    def _a_media_shuffle(self, a: dict) -> Any:
        self.media["shuffle"] = not self.media.get("shuffle")
        self._emit_media()

    def _a_media_repeat(self, a: dict) -> Any:
        order = ["off", "all", "one"]
        self.media["repeat"] = order[(order.index(self.media.get("repeat", "off")) + 1) % 3]
        self._emit_media()

    def _a_media_launch(self, a: dict) -> Any:
        self.media.update(session=True, playing=False)
        self._emit_media()

    # --- notifications
    def _a_notification_dismiss(self, a: dict) -> Any:
        n = self._find("notifications", a.get("id", ""))
        if n and n.get("kind") == "confirm" and n["id"] in self._pending:
            return self._a_confirm_respond({"id": n["id"], "approve": False})
        self._remove("notifications", a.get("id", ""))
        return None

    def _a_notification_read_all(self, a: dict) -> Any:
        for n in list(self.data["notifications"]):
            if not n.get("read") and n.get("kind") != "confirm":
                self._update("notifications", n["id"], read=True)
        return None

    # --- agent tasks / routines
    def _a_agent_task_reorder(self, a: dict) -> Any:
        active = sorted([t for t in self.data["agent.tasks"] if not t["archived"]], key=lambda t: t["order"])
        it = next((t for t in active if t["id"] == a.get("id")), None)
        if it is None or it["status"] != "queued":
            return "only queued tasks can be reordered"
        active.remove(it)
        active.insert(max(0, min(int(a.get("index", 0)), len(active))), it)
        for i, t in enumerate(active):
            if t["order"] != i:
                self._update("agent.tasks", t["id"], order=i)
        return None

    def _a_agent_task_pause(self, a: dict) -> Any:
        t = self._find("agent.tasks", a.get("id", ""))
        if not t or t["status"] not in ("running", "queued"):
            return "that task cannot be paused now"
        self._update("agent.tasks", t["id"], status="paused", _was=t["status"], meta="paused")
        return None

    def _a_agent_task_resume(self, a: dict) -> Any:
        t = self._find("agent.tasks", a.get("id", ""))
        if not t or t["status"] != "paused":
            return "that task is not paused"
        self._update("agent.tasks", t["id"], status=t.get("_was", "queued"), meta="~30s" if t.get("_was") == "running" else "next")
        return None

    def _a_agent_task_cancel(self, a: dict) -> Any:
        t = self._find("agent.tasks", a.get("id", ""))
        if not t or t["archived"]:
            return "no such task"
        self._finish_task(t, "cancelled", "cancelled")
        return None

    def _a_routine_toggle(self, a: dict) -> Any:
        r = self._find("routines", a.get("id", ""))
        if not r:
            return "no such routine"
        self._update("routines", r["id"], enabled=not r["enabled"])
        return None

    # --- commands (create is T2: standing commands can trigger tools)
    def _a_command_create(self, a: dict) -> Any:
        text, trigger = str(a.get("text", "")).strip(), str(a.get("trigger", "")).strip()
        trig = tu.parse_trigger(trigger)
        if not text:
            return "the command is empty"
        if not trig.get("ok"):
            return trig.get("human", "unknown trigger")

        def decide(ok: bool) -> None:
            if ok:
                self._add("commands", self._command(_id("cm"), text[:200], trigger, last="new"), 0)

        return self._confirm("Create standing command", f"command_create · “{text[:80]}” · {trig['chip']}", 2, decide, tool="command_create")

    def _a_command_update(self, a: dict) -> Any:
        c = self._find("commands", a.get("id", ""))
        if not c:
            return "no such command"
        fields: dict[str, Any] = {}
        if "text" in a:
            fields["text"] = str(a["text"])[:200]
        if "trigger" in a:
            trig = tu.parse_trigger(str(a["trigger"]))
            if not trig.get("ok"):
                return trig.get("human")
            fields.update(trigger=a["trigger"], chip=trig["chip"], kind=trig["kind"], next=float(trig.get("next") or 0), period=float(trig.get("period") or 0), _trig=trig)
            fields["prev"] = fields["next"] - fields["period"] if fields["period"] else 0
        self._update("commands", c["id"], **fields)
        return None

    def _a_command_delete(self, a: dict) -> Any:
        self._remove("commands", a.get("id", ""))
        return None

    def _a_command_pause(self, a: dict) -> Any:
        return None if self._update("commands", a.get("id", ""), paused=True) else "no such command"

    def _a_command_resume(self, a: dict) -> Any:
        c = self._find("commands", a.get("id", ""))
        if not c:
            return "no such command"
        nxt = tu.advance_trigger(c.get("_trig", {})) if c.get("period") else c.get("next", 0)
        self._update("commands", c["id"], paused=False, next=nxt, prev=nxt - c["period"] if c.get("period") else 0)
        return None

    def _a_command_run_now(self, a: dict) -> Any:
        c = self._find("commands", a.get("id", ""))
        if not c:
            return "no such command"
        self._fire_command(c, manual=True)
        return None

    # --- voice
    def _a_activation_ptt(self, a: dict) -> Any:
        if a.get("down"):
            self._ptt = True
            self._set_state("listening")
        elif self._ptt:
            self._ptt = False
            self._set_state("thinking")
            QTimer.singleShot(1400, lambda: self._ptt or self._set_state("speaking"))
            QTimer.singleShot(4200, lambda: self._ptt or self._set_state("idle"))
        return None

    # --- demo controls (not part of the real protocol)
    def _a_dev_state(self, a: dict) -> Any:
        self.cycle = False
        self._set_state(str(a.get("state", "idle")))

    def _a_dev_next_state(self, a: dict) -> Any:
        self.cycle = False
        self._cycle_i = (STATE_CYCLE.index(self.state) + 1) % len(STATE_CYCLE) if self.state in STATE_CYCLE else 0
        self._set_state(STATE_CYCLE[self._cycle_i])

    def _a_dev_cycle(self, a: dict) -> Any:
        self.cycle = not self.cycle

    def _a_dev_clap(self, a: dict) -> Any:
        self._clap_at = time.time()

    def _a_dev_fail_next(self, a: dict) -> Any:
        self._fail_next = True

    def _a_dev_ring_alarm(self, a: dict) -> Any:
        self._ring_demo_alarm()

    def _a_dev_fire_reminder(self, a: dict) -> Any:
        rid = _id("rm")
        self._add("reminders", {"id": rid, "text": "Stand up and stretch", "at": time.time() + 2, "done": False, "due": False, "untrusted": False})

    def _a_dev_notify(self, a: dict) -> Any:
        self._add("notifications", {"id": _id("nt"), "kind": "telegram", "title": "Telegram · Atlas group", "text": random.choice([
            "Bench rig is free after 4, want it?", "Pushed the new servo firmware, can you flash it tonight?", "<b>click here</b> https://example.com/free-gpu (do not trust me)"]),
            "ts": time.time(), "read": False, "untrusted": True}, 0)

    def _a_dev_confirm(self, a: dict) -> Any:
        return self._confirm("Delete 3 old notes", "note_delete · 3 notes older than 90 days", 3, lambda ok: None, tool="note_delete")

    # ================================================================== simulation
    def _on_tick(self) -> None:
        now = time.time()
        # reminders coming due
        for r in self.data["reminders"]:
            if not r["done"] and not r["due"] and r["at"] <= now:
                self._update("reminders", r["id"], due=True)
                self._event("reminder.due", id=r["id"], text=r["text"])
                self._add("notifications", {"id": _id("nt"), "kind": "reminder", "title": "Reminder", "text": r["text"], "ts": now, "read": False, "untrusted": False}, 0)
        # alarms
        for al in self.data["alarms"]:
            if al["ringing"]:
                if now - al.get("_rang", now) > 45:
                    self._a_alarm_stop({"id": al["id"]})
                continue
            snooze = al.get("_snooze_until")
            if snooze and now >= snooze:
                al.pop("_snooze_until", None)
                self._ring(al)
                continue
            if al["enabled"]:
                nxt = al.get("_next") or tu.next_alarm(al["hour"], al["minute"], al["days"], now - 1)
                al["_next"] = nxt
                if now >= nxt:
                    al.pop("_next", None)
                    self._ring(al)
            else:
                al.pop("_next", None)
        # standing commands
        for c in self.data["commands"]:
            if not c["paused"] and c.get("next") and now >= c["next"]:
                self._fire_command(c)
        # media position (the UI interpolates between these ticks)
        if self.media.get("playing"):
            self.media["position"] = float(self.media.get("position", 0)) + 1.0
            if self.media["position"] >= self.media.get("duration", 1):
                if self.media.get("repeat") == "one":
                    self.media["position"] = 0.0
                    self._emit_media()
                else:
                    self._track(1)
            elif "media.now_playing" in self.subs:
                self._emit({"type": "media.now_playing", "op": "tick", "position": self.media["position"], "playing": True})
        # routine run at 19:00 / evening brief: the demo leaves it queued

    def _ring(self, al: dict) -> None:
        al["_rang"] = time.time()
        self._update("alarms", al["id"], ringing=True)
        self._event("alarm.ringing", id=al["id"], label=al["label"], hour=al["hour"], minute=al["minute"])

    def _ring_demo_alarm(self) -> None:
        al = self._find("alarms", "al_demo")
        if al is None:
            t = tu.local(time.time())
            al = {"id": "al_demo", "hour": t.hour, "minute": t.minute, "label": "Demo alarm", "days": [], "enabled": False, "ringing": False}
            self._add("alarms", al)
        self._ring(al)

    def _fire_command(self, c: dict, manual: bool = False) -> None:
        now = time.time()
        if not manual and c.get("period"):
            nxt = tu.advance_trigger(c.get("_trig", {}), now)
            self._update("commands", c["id"], next=nxt, prev=now, last="running…")
        elif not manual:
            self._update("commands", c["id"], next=0, last="running…")
        else:
            self._update("commands", c["id"], last="running…")
        self._event("command.fired", id=c["id"])
        tid = _id("tk")
        active = [t for t in self.data["agent.tasks"] if not t["archived"]]
        self._add("agent.tasks", {"id": tid, "title": c["text"][:1].upper() + c["text"][1:], "source": "command", "status": "running", "meta": "~20s",
                                  "order": -1, "progress": 0.0, "archived": False, "finished": 0, "steps": [{"text": "started by standing command", "state": "done"}],
                                  "_plan": ["open the lab inbox (IMAP)", "classify 4 new messages", "notify you of 1 that needs a reply"], "_cmd": c["id"],
                                  "detail": f"Standing command · {c['chip']}"}, 0)
        del active

    def _advance_tasks(self) -> None:
        now = time.time()
        tasks = self.data["agent.tasks"]
        running = [t for t in tasks if t["status"] == "running" and not t["archived"]]
        for t in running:
            steps = [dict(s) for s in t["steps"]]
            for s in steps:
                if s["state"] == "running":
                    s["state"] = "done"
            plan = t.get("_plan") or []
            if plan:
                steps.append({"text": plan.pop(0), "state": "running"})
                total = len(steps) + len(plan)
                prog = (len(steps) - 1) / max(1, total) if t.get("progress", -1) >= 0 else -1
                self._update("agent.tasks", t["id"], steps=steps, progress=prog, meta=f"~{max(5, 13 * (len(plan) + 1))}s")
            else:
                self._update("agent.tasks", t["id"], steps=steps)
                self._finish_task(t, "done", tu.local(now).strftime("%H:%M"))
        # start the next queued "you"/"command" task when nothing is running
        if not any(t["status"] == "running" and not t["archived"] for t in tasks):
            q = sorted([t for t in tasks if t["status"] == "queued" and not t["archived"] and t["source"] in ("you", "command", "agent")], key=lambda t: t["order"])
            if q:
                self._update("agent.tasks", q[0]["id"], status="running", meta="~40s")

    def _finish_task(self, t: dict, status: str, meta: str) -> None:
        now = time.time()
        self._update("agent.tasks", t["id"], status=status, meta=meta, finished=now, progress=1 if status == "done" else t.get("progress", -1))
        if status == "done":
            self._add("notifications", {"id": _id("nt"), "kind": "task", "title": "Task done", "text": t["title"], "ts": now, "read": False, "untrusted": False}, 0)
        cid = t.get("_cmd")
        if cid:
            self._update("commands", cid, last="ok just now" if status == "done" else status)
        QTimer.singleShot(1500, lambda i=t["id"]: self._archive(i))

    def _archive(self, tid: str) -> None:
        t = self._find("agent.tasks", tid)
        if t is None:
            return
        self._update("agent.tasks", tid, archived=True)
        done = sorted([x for x in self.data["agent.tasks"] if x["archived"]], key=lambda x: -x["finished"])
        for old in done[10:]:
            self._remove("agent.tasks", old["id"])

    def _on_cycle(self) -> None:
        if not self.cycle or self._ptt:
            return
        self._cycle_i = (STATE_CYCLE.index(self.state) + 1) % len(STATE_CYCLE) if self.state in STATE_CYCLE else 0
        self._set_state(STATE_CYCLE[self._cycle_i])

    # ------------------------------------------------------------------ spectrum
    def _on_spectrum(self) -> None:
        t = time.time()
        st = self.state
        clap = False
        if t >= self._clap_at:
            clap = True
            self._clap_at = t + random.uniform(9, 16)
        if st in ("listening", "speaking"):
            syll = max(0.0, math.sin(2 * math.pi * (3.9 if st == "listening" else 4.6) * t + 2.5 * math.sin(0.7 * t)))
            phrase = 1.0 if math.sin(2 * math.pi * t / (5.0 if st == "listening" else 3.7)) > -0.55 else 0.12
            env = (0.25 + 0.75 * syll ** 0.6) * phrase * (0.75 + 0.25 * math.sin(0.31 * t))
        else:
            env = 0.16 + 0.05 * math.sin(1.3 * t)
        f1 = 5 + 3 * math.sin(0.9 * t)
        f2 = 13 + 4 * math.sin(0.62 * t + 1)
        f3 = 22 + 3 * math.sin(0.47 * t + 2)
        bands = []
        for b in range(32):
            pink = 1.0 - b / 42
            form = math.exp(-((b - f1) / 2.4) ** 2) + 0.8 * math.exp(-((b - f2) / 2.6) ** 2) + 0.55 * math.exp(-((b - f3) / 2.2) ** 2)
            v = env * (0.35 * pink + 0.65 * form) * random.uniform(0.8, 1.15) + 0.03 * random.random()
            if clap:
                v = max(v, 0.85 + 0.1 * random.random())
            bands.append(int(max(0, min(255, v * 255))))
        rms = int(sum(bands) / len(bands))
        typ = "tts.spectrum" if st == "speaking" else "audio.spectrum"
        if typ in self.subs:
            self._emit({"type": typ, "ts": t, "bands": bands, "rms": rms, "clap": clap})

    # ------------------------------------------------------------------ the 60 s demo script
    def _build_script(self) -> None:
        def notify() -> None:
            self._add("notifications", {"id": _id("nt"), "kind": "telegram", "title": "Telegram · Lab group", "text": "GRN samples are ready for imaging. Slot open at 16:00?",
                                        "ts": time.time(), "read": False, "untrusted": True}, 0)

        def reminder() -> None:
            self._add("reminders", {"id": _id("rm"), "text": "Stretch break", "at": time.time() + 13, "done": False, "due": False, "untrusted": False})

        def confirm() -> None:
            self._a_dev_confirm({})

        self._script = [(8, notify), (15, reminder), (40, confirm), (58, self._ring_demo_alarm)]

    def _on_script(self) -> None:
        el = time.time() - self.t0
        while self._script and self._script[0][0] <= el:
            _, fn = self._script.pop(0)
            fn()
        if not self._script:
            self._scr.stop()

    # ------------------------------------------------------------------ connection (demo of offline state)
    def set_online(self, on: bool) -> None:
        self.online = on
        if not on:
            self.client = False
            self.subs.clear()
            self._spec_update()
