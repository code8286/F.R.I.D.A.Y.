# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""The UI's view of the core (exposed to QML as the `Core` singleton).

It holds one master store per topic (snapshot + deltas, stable ids), derives the list models QML shows, computes
the glance values, and sends every user action to the core as {type: "action", id, name, args}. Cheap reversible
actions are applied optimistically and rolled back (with a shake) if the core says no. Anything that can produce
a confirmation is never optimistic. The transport is the in-process mock today and the WebSocket client in
tranche 4: it only needs `send(dict)`, `connect_client() -> bool` and a `message(dict)` signal.

Upcoming (tile A) is merged here in the UI from calendar, reminders and alarms (brief section 5A: we chose the
UI-side merge, so the core does not need a fourth copy of the same data).
"""

from __future__ import annotations

import math
import time
import uuid
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import timeutil as tu
from .models import ItemModel

TOPICS = ["activation.state", "audio.spectrum", "tts.spectrum", "calendar.events", "reminders", "todos", "alarms", "media.now_playing",
          "notifications", "agent.tasks", "routines", "commands"]
LIST_TOPICS = ["calendar.events", "reminders", "todos", "alarms", "notifications", "agent.tasks", "routines", "commands"]
OPTIMISTIC = {"todo.toggle", "todo.reorder", "reminder.snooze", "reminder.done", "alarm.toggle", "routine.toggle", "media.play_pause", "agent_task.reorder"}


class Bridge(QObject):
    stateChanged = Signal()
    connectedChanged = Signal()
    statsChanged = Signal()
    mediaChanged = Signal()
    nowChanged = Signal()
    rmsChanged = Signal()
    flagsChanged = Signal()
    spectrumFrame = Signal(list, int, bool, str)
    coreEvent = Signal(str, "QVariantMap")
    actionResult = Signal(str, bool, str)

    def __init__(self, transport: Any, parent: Any = None):
        super().__init__(parent)
        self.t = transport
        self.t.message.connect(self._on_message)
        self._state = "idle"
        self._connected = False
        self._now = time.time()
        self._rms_db = -60.0
        self._rms_acc: list[float] = []
        self._stats: dict = {}
        self._media: dict = {}
        self._store: dict[str, dict] = {t: {"order": [], "items": {}} for t in LIST_TOPICS}
        self._pending: dict[str, tuple[str, Callable[[], None], str]] = {}
        self._spectrum_wanted = True
        self._backoff = 0.5
        self.autoCycle = True

        keys_todo = ["text", "done", "priority", "due", "order", "done_at", "untrusted"]
        keys_rem = ["text", "at", "done", "due", "untrusted"]
        self._views: dict[str, tuple[ItemModel, str, Callable[[dict], bool], Callable[[dict], Any], int]] = {}
        self._view("todoOpen", keys_todo, "todos", lambda i: not i["done"], lambda i: i.get("order", 0))
        self._view("todoDone", keys_todo, "todos", lambda i: bool(i["done"]), lambda i: -float(i.get("done_at") or 0), 20)
        self._view("remOverdue", keys_rem, "reminders", lambda i: not i["done"] and (i.get("due") or i["at"] <= self._now), lambda i: i["at"])
        self._view("remToday", keys_rem, "reminders", lambda i: not i["done"] and not i.get("due") and i["at"] > self._now and tu.same_day(i["at"], self._now), lambda i: i["at"])
        self._view("remLater", keys_rem, "reminders", lambda i: not i["done"] and not i.get("due") and i["at"] > self._now and not tu.same_day(i["at"], self._now), lambda i: i["at"])
        self._view("alarms", ["hour", "minute", "label", "days", "enabled", "ringing"], "alarms", lambda i: True, lambda i: i["hour"] * 60 + i["minute"])
        self._view("events", ["title", "calendar", "start", "end", "location", "notes"], "calendar.events", lambda i: True, lambda i: i["start"])
        self._view("notifications", ["kind", "title", "text", "ts", "read", "untrusted", "tier", "action", "tool", "resolved"], "notifications", lambda i: True,
                   lambda i: (0 if i.get("kind") == "confirm" and not i.get("resolved") else 1, -float(i.get("ts") or 0)))
        task_keys = ["title", "source", "status", "meta", "order", "progress", "archived", "finished", "steps", "detail"]
        self._view("tasksActive", task_keys, "agent.tasks", lambda i: not i.get("archived"), lambda i: i.get("order", 0))
        self._view("tasksRecent", task_keys, "agent.tasks", lambda i: bool(i.get("archived")), lambda i: -float(i.get("finished") or 0), 10)
        self._view("routines", ["title", "enabled"], "routines", lambda i: True, lambda i: 0)
        self._view("commands", ["text", "trigger", "chip", "kind", "next", "prev", "period", "last", "paused", "untrusted"], "commands", lambda i: True, lambda i: 0)
        self._upcoming = ItemModel(["title", "label", "at", "source", "sourceLetter"], self)
        self._resync()          # every stats key exists before the first snapshot arrives

        self._clock = QTimer(self, interval=1000, timeout=self._on_clock)
        self._clock.start()
        self._rms_timer = QTimer(self, interval=160, timeout=self._on_rms)
        self._rms_timer.start()
        self._retry = QTimer(self, singleShot=True, timeout=self._connect)
        QTimer.singleShot(0, self._connect)

    # ================================================================== views
    def _view(self, name: str, keys: list[str], topic: str, flt: Callable[[dict], bool], key: Callable[[dict], Any], limit: int = 0) -> None:
        self._views[name] = (ItemModel(keys, self), topic, flt, key, limit)

    def _resync(self, topic: str | None = None) -> None:
        st_cache: dict[str, list[dict]] = {}
        for _name, (model, top, flt, key, limit) in self._views.items():
            if topic is not None and top != topic:
                continue
            if top not in st_cache:
                st = self._store[top]
                st_cache[top] = [st["items"][i] for i in st["order"] if i in st["items"]]
            items = [i for i in st_cache[top] if flt(i)]
            items.sort(key=key)
            if limit:
                items = items[:limit]
            model.sync(items)
        if topic in (None, "calendar.events", "reminders", "alarms"):
            self._upcoming.sync(self._compute_upcoming())
        self._compute_stats()

    def _model(name: str) -> Property:  # type: ignore[misc]
        return Property(QObject, lambda self: self._views[name][0], constant=True)

    todoOpen = _model("todoOpen")
    todoDone = _model("todoDone")
    remOverdue = _model("remOverdue")
    remToday = _model("remToday")
    remLater = _model("remLater")
    alarms = _model("alarms")
    events = _model("events")
    notifications = _model("notifications")
    tasksActive = _model("tasksActive")
    tasksRecent = _model("tasksRecent")
    routines = _model("routines")
    commands = _model("commands")
    upcoming = Property(QObject, lambda self: self._upcoming, constant=True)
    del _model

    def _items(self, topic: str) -> list[dict]:
        st = self._store[topic]
        return [st["items"][i] for i in st["order"] if i in st["items"]]

    def _compute_upcoming(self) -> list[dict]:
        now, horizon = self._now, self._now + 24 * 3600
        out: list[dict] = []
        for e in self._items("calendar.events"):
            if now - 60 < e["start"] <= horizon:
                out.append({"id": "u_" + e["id"], "title": e["title"], "label": e.get("calendar", ""), "at": e["start"], "source": "calendar", "sourceLetter": "B"})
        for r in self._items("reminders"):
            if not r["done"] and now < r["at"] <= horizon:
                out.append({"id": "u_" + r["id"], "title": r["text"], "label": "Reminder", "at": r["at"], "source": "reminder", "sourceLetter": "C"})
        for a in self._items("alarms"):
            if a["enabled"]:
                at = tu.next_alarm(a["hour"], a["minute"], a["days"], now)
                if at <= horizon:
                    out.append({"id": "u_" + a["id"], "title": a["label"], "label": "Alarm", "at": at, "source": "alarm", "sourceLetter": "E"})
        out.sort(key=lambda i: i["at"])
        return out

    def _compute_stats(self) -> None:
        now = self._now
        todos = self._items("todos")
        open_t = sorted([t for t in todos if not t["done"]], key=lambda t: t.get("order", 0))
        due_today = [t for t in open_t if t.get("due") and tu.same_day(t["due"], now)]
        rem = [r for r in self._items("reminders") if not r["done"]]
        rem_today = [r for r in rem if tu.same_day(r["at"], now) or r.get("due")]
        rem_next = min((r for r in rem if r["at"] > now and not r.get("due")), key=lambda r: r["at"], default=None)
        alarms = []
        for a in self._items("alarms"):
            if a["enabled"]:
                alarms.append((tu.next_alarm(a["hour"], a["minute"], a["days"], now), a))
        alarms.sort(key=lambda x: x[0])
        ringing = next((a for a in self._items("alarms") if a.get("ringing")), None)
        ev = self._items("calendar.events")
        ev_next = min((e for e in ev if e["start"] > now - 60), key=lambda e: e["start"], default=None)
        d = tu.local(now)
        week_start = (d.replace(hour=0, minute=0, second=0, microsecond=0)).timestamp() - d.weekday() * 86400
        week = [any(week_start + k * 86400 <= e["start"] < week_start + (k + 1) * 86400 for e in ev) for k in range(7)]
        notes = self._items("notifications")
        unread = sum(1 for n in notes if not n.get("read"))
        confirms = [n for n in notes if n.get("kind") == "confirm" and not n.get("resolved")]
        tasks = [t for t in self._items("agent.tasks") if not t.get("archived")]
        running = sum(1 for t in tasks if t["status"] == "running")
        awaiting = sum(1 for t in tasks if t["status"] == "awaiting")
        cmds = self._items("commands")
        up = self._upcoming.items()
        self._stats = {
            "todoOpen": len(open_t), "todoDueToday": len(due_today), "todoFirst": open_t[0]["text"] if open_t else "",
            "todoFirstUntrusted": bool(open_t and open_t[0].get("untrusted")),
            "remToday": len(rem_today), "remNextText": rem_next["text"] if rem_next else "", "remNextAt": rem_next["at"] if rem_next else 0,
            "remOverdue": sum(1 for r in rem if r.get("due") or r["at"] <= now),
            "alarmNextAt": alarms[0][0] if alarms else 0, "alarmNextLabel": alarms[0][1]["label"] if alarms else "",
            "alarmNextHour": alarms[0][1]["hour"] if alarms else 0, "alarmNextMinute": alarms[0][1]["minute"] if alarms else 0,
            "alarmNextDays": alarms[0][1]["days"] if alarms else [], "alarmRinging": ringing["id"] if ringing else "",
            "alarmRingingLabel": ringing["label"] if ringing else "", "alarmCount": len(self._items("alarms")),
            "eventNextTitle": ev_next["title"] if ev_next else "", "eventNextAt": ev_next["start"] if ev_next else 0,
            "eventNextCalendar": ev_next.get("calendar", "") if ev_next else "",
            "week": week, "weekday": d.weekday(),
            "unread": unread, "confirms": len(confirms), "confirmFirst": confirms[0]["id"] if confirms else "",
            "upNextTitle": up[0]["title"] if up else "", "upNextLabel": up[0]["label"] if up else "", "upNextAt": up[0]["at"] if up else 0,
            "upNextSource": up[0]["source"] if up else "",
            "tasksRunning": running, "tasksQueued": sum(1 for t in tasks if t["status"] in ("queued", "awaiting")),
            "tasksAwaiting": awaiting,
            "cmdStanding": len(cmds), "cmdPaused": sum(1 for c in cmds if c.get("paused")),
        }
        self.statsChanged.emit()

    stats = Property("QVariantMap", lambda self: self._stats, notify=statsChanged)

    # ================================================================== simple properties
    state = Property(str, lambda self: self._state, notify=stateChanged)
    connected = Property(bool, lambda self: self._connected, notify=connectedChanged)
    media = Property("QVariantMap", lambda self: self._media, notify=mediaChanged)
    now = Property(float, lambda self: self._now, notify=nowChanged)
    rmsDb = Property(float, lambda self: self._rms_db, notify=rmsChanged)

    def _get_cycle(self) -> bool:
        return bool(getattr(self.t, "cycle", False))

    cycling = Property(bool, _get_cycle, notify=flagsChanged)

    # ================================================================== connection
    def _connect(self) -> None:
        if self.t.connect_client():
            self._backoff = 0.5
            self._set_connected(True)
            topics = [t for t in TOPICS if self._spectrum_wanted or "spectrum" not in t]
            self.t.send({"type": "subscribe", "topics": topics})
        else:
            self._set_connected(False)
            self._retry.start(int(self._backoff * 1000))
            self._backoff = min(8.0, self._backoff * 2)

    def _set_connected(self, on: bool) -> None:
        if on != self._connected:
            self._connected = on
            self.connectedChanged.emit()

    # ================================================================== incoming
    def _on_message(self, msg: dict) -> None:
        typ = msg.get("type", "")
        if typ in self._store:
            self._apply(typ, msg)
            self._resync(typ)
        elif typ in ("audio.spectrum", "tts.spectrum"):
            bands = [int(b) for b in msg.get("bands", [])][:32]
            rms = int(msg.get("rms", 0))
            self._rms_acc.append(rms / 255.0)
            self.spectrumFrame.emit(bands, rms, bool(msg.get("clap")), "tts" if typ == "tts.spectrum" else "mic")
            if msg.get("clap"):
                self.coreEvent.emit("clap", {})
        elif typ == "activation.state":
            st = str(msg.get("state", "idle"))
            if st != self._state:
                self._state = st
                self.stateChanged.emit()
        elif typ == "media.now_playing":
            m = dict(self._media)
            if msg.get("op") == "tick":
                m.update(position=float(msg.get("position", 0)), playing=bool(msg.get("playing", True)))
            else:
                m = {k: v for k, v in msg.items() if k not in ("type", "op")}
            m["receivedAt"] = time.time()
            if m.get("track_id") != self._media.get("track_id") and self._media:
                self.coreEvent.emit("media.track", {"track_id": m.get("track_id", "")})
            self._media = m
            self.mediaChanged.emit()
        elif typ == "action.result":
            self._on_result(msg)
        elif typ == "event":
            name = str(msg.get("name", ""))
            self.coreEvent.emit(name, {k: v for k, v in msg.items() if k not in ("type", "name")})
        if typ == "activation.state":
            self.flagsChanged.emit()

    def _apply(self, topic: str, msg: dict) -> None:
        st = self._store[topic]
        op = msg.get("op")
        if op == "snapshot":
            items = msg.get("items", [])
            st["order"] = [i["id"] for i in items]
            st["items"] = {i["id"]: dict(i) for i in items}
        elif op == "add":
            it = dict(msg["item"])
            if it["id"] in st["items"]:
                st["order"].remove(it["id"])
            idx = msg.get("index")
            idx = len(st["order"]) if idx is None else max(0, min(int(idx), len(st["order"])))
            st["order"].insert(idx, it["id"])
            st["items"][it["id"]] = it
        elif op == "update":
            it = msg["item"]
            if it["id"] in st["items"]:
                st["items"][it["id"]].update(it)
            else:
                st["items"][it["id"]] = dict(it)
                st["order"].append(it["id"])
        elif op == "remove":
            iid = msg.get("id")
            st["items"].pop(iid, None)
            if iid in st["order"]:
                st["order"].remove(iid)
        elif op == "move":
            iid = msg.get("id")
            if iid in st["order"]:
                st["order"].remove(iid)
                st["order"].insert(max(0, min(int(msg.get("index", 0)), len(st["order"]))), iid)

    def _on_result(self, msg: dict) -> None:
        aid = msg.get("id", "")
        ok = bool(msg.get("ok"))
        err = str(msg.get("error", ""))
        pend = self._pending.pop(aid, None)
        if pend is not None and not ok:
            name, rollback, item_id = pend
            rollback()
            self.coreEvent.emit("action.rejected", {"name": name, "itemId": item_id, "error": err})
        elif not ok:
            self.coreEvent.emit("action.rejected", {"name": "", "itemId": "", "error": err})
        if msg.get("pending"):
            self.coreEvent.emit("confirm.pending", {"id": msg.get("confirm_id", "")})
        self.actionResult.emit(aid, ok, err)

    # ================================================================== actions
    @Slot(str, "QVariantMap", result=str)
    def action(self, name: str, args: dict) -> str:
        if not self._connected:
            self.coreEvent.emit("action.rejected", {"name": name, "itemId": str(args.get("id", "")), "error": "core offline"})
            return ""
        aid = uuid.uuid4().hex
        args = dict(args or {})
        if name in OPTIMISTIC:
            rb = self._optimistic(name, args)
            if rb is not None:
                self._pending[aid] = (name, rb, str(args.get("id", "")))
        self.t.send({"type": "action", "id": aid, "name": name, "args": args})
        return aid

    def _snapshot_item(self, topic: str, iid: str) -> Callable[[], None]:
        st = self._store[topic]
        prev = dict(st["items"][iid]) if iid in st["items"] else None
        order = list(st["order"])

        def rollback() -> None:
            if prev is not None:
                st["items"][iid] = prev
            st["order"] = order
            self._resync(topic)

        return rollback

    def _optimistic(self, name: str, a: dict) -> Callable[[], None] | None:
        iid = str(a.get("id", ""))
        if name == "media.play_pause":
            prev = dict(self._media)

            def rb() -> None:
                self._media = prev
                self.mediaChanged.emit()

            m = dict(self._media)
            m["position"] = self.mediaPosition()
            m["receivedAt"] = time.time()
            m["playing"] = not m.get("playing", False)
            self._media = m
            self.mediaChanged.emit()
            return rb
        topic = {"todo": "todos", "reminder": "reminders", "alarm": "alarms", "routine": "routines", "agent_task": "agent.tasks"}[name.split(".")[0]]
        items = self._store[topic]["items"]
        if iid not in items:
            return None
        rb = self._snapshot_item(topic, iid)
        it = items[iid]
        if name == "todo.toggle":
            done = not it["done"] if "done" not in a else bool(a["done"])
            it.update(done=done, done_at=time.time() if done else 0)
        elif name == "todo.reorder" or name == "agent_task.reorder":
            if name == "todo.reorder":
                group = sorted([t for t in items.values() if not t["done"]], key=lambda t: t["order"])
            else:
                group = sorted([t for t in items.values() if not t.get("archived")], key=lambda t: t["order"])
            if it not in group:
                return None
            group.remove(it)
            group.insert(max(0, min(int(a.get("index", 0)), len(group))), it)
            for i, t in enumerate(group):
                t["order"] = i
        elif name == "reminder.snooze":
            it.update(at=tu.snooze_target(str(a.get("choice", "15m"))), due=False)
        elif name == "reminder.done":
            it.update(done=True, due=False)
        elif name in ("alarm.toggle", "routine.toggle"):
            it["enabled"] = not it["enabled"]
        self._resync(topic)
        return rb

    @Slot(str, "QVariantMap")
    def dev(self, name: str, args: dict) -> None:
        """Demo controls. Some act on the transport directly (connection), the rest are mock-core actions."""
        if name == "offline":
            on = not self._connected
            if hasattr(self.t, "set_online"):
                self.t.set_online(on)
            if on:
                self._retry.stop()
                self._backoff = 0.5
                self._connect()
            else:
                self._set_connected(False)
                self._backoff = 0.5
                self._retry.start(500)
            return
        if not self._connected:
            return
        self.t.send({"type": "action", "id": uuid.uuid4().hex, "name": "dev." + name, "args": dict(args or {})})
        QTimer.singleShot(300, self.flagsChanged.emit)

    @Slot(bool)
    def setSpectrumWanted(self, on: bool) -> None:  # noqa: N802
        """The window was hidden / minimised (or shown again): stop / restart the spectrum subscription."""
        if on == self._spectrum_wanted:
            return
        self._spectrum_wanted = on
        if self._connected:
            self.t.send({"type": "subscribe" if on else "unsubscribe", "topics": ["audio.spectrum", "tts.spectrum"]})

    # ================================================================== helpers for QML
    @Slot(result=float)
    def mediaPosition(self) -> float:  # noqa: N802
        m = self._media
        if not m:
            return 0.0
        pos = float(m.get("position", 0))
        if m.get("playing"):
            pos += time.time() - float(m.get("receivedAt", time.time()))
        return max(0.0, min(pos, float(m.get("duration", 1) or 1)))

    @Slot(int, int, int, result="QVariantList")
    def eventsOn(self, y: int, m: int, d: int) -> list:  # noqa: N802 - month is 1-based
        out = []
        for e in self._items("calendar.events"):
            ld = tu.local(e["start"])
            if (ld.year, ld.month, ld.day) == (y, m, d):
                out.append(dict(e))
        out.sort(key=lambda e: e["start"])
        return out

    @Slot(int, int, result="QVariantList")
    def eventDays(self, y: int, m: int) -> list:  # noqa: N802
        days = set()
        for e in self._items("calendar.events"):
            ld = tu.local(e["start"])
            if ld.year == y and ld.month == m:
                days.add(ld.day)
        return sorted(days)

    @Slot(str, result="QVariantMap")
    def parseTrigger(self, text: str) -> dict:  # noqa: N802
        return tu.parse_trigger(text)

    @Slot(int, int, "QVariantList", result=float)
    def nextAlarmAt(self, hour: int, minute: int, days: list) -> float:  # noqa: N802
        return tu.next_alarm(hour, minute, [int(x) for x in days])

    @Slot(str, result=float)
    def snoozeTarget(self, choice: str) -> float:  # noqa: N802
        return tu.snooze_target(choice)

    @Slot(int, int, result=float)
    def todayAt(self, hour: int, minute: int) -> float:  # noqa: N802
        return tu.at_today(hour, minute)

    # ================================================================== timers
    def _on_clock(self) -> None:
        self._now = time.time()
        self.nowChanged.emit()
        if int(self._now) % 20 == 0:
            for topic in ("reminders", "calendar.events"):
                self._resync(topic)
        else:
            self._compute_stats()

    def _on_rms(self) -> None:
        if not self._rms_acc:
            return
        v = max(1e-4, sum(self._rms_acc) / len(self._rms_acc))
        self._rms_acc.clear()
        db = 20 * math.log10(v) - 8
        self._rms_db = max(-90.0, min(0.0, db))
        self.rmsChanged.emit()

    def feed_external(self, bands: list[int], rms: int, clap: bool) -> None:
        """--mock-mic: real microphone bands computed in this process (the core is not running)."""
        self._rms_acc.append(rms / 255.0)
        self.spectrumFrame.emit(bands, rms, clap, "mic")
        if clap:
            self.coreEvent.emit("clap", {})
