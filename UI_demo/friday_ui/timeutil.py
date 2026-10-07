# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Time helpers shared by the UI bridge and the mock core (pure Python, no Qt)."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

DAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"]
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def local(ts: float) -> datetime:
    return datetime.fromtimestamp(ts)


def at_today(hour: int, minute: int, now: float | None = None) -> float:
    d = local(now if now is not None else time.time())
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


def same_day(a: float, b: float) -> bool:
    return local(a).date() == local(b).date()


def next_alarm(hour: int, minute: int, days: list[int], now: float | None = None) -> float:
    """Next time an alarm with these weekdays (0 = Monday; empty = every day) rings."""
    now = time.time() if now is None else now
    base = local(now).replace(hour=hour, minute=minute, second=0, microsecond=0)
    for add in range(0, 8):
        cand = base + timedelta(days=add)
        if cand.timestamp() <= now:
            continue
        if not days or cand.weekday() in days:
            return cand.timestamp()
    return (base + timedelta(days=1)).timestamp()


def snooze_target(choice: str, now: float | None = None) -> float:
    now = time.time() if now is None else now
    if choice == "tomorrow":
        d = local(now) + timedelta(days=1)
        return d.replace(hour=9, minute=0, second=0, microsecond=0).timestamp()
    minutes = {"5m": 5, "15m": 15, "1h": 60}.get(choice, 10)
    return now + minutes * 60


# --------------------------------------------------------------------------- command triggers
def parse_trigger(text: str, now: float | None = None) -> dict:
    """Parse a human trigger ("daily 08:00", "every 2h", "weekdays 18:30", "on wake", "once 14:30", "sun 10:00").

    Returns {ok, kind, chip, human, period, next}. `chip` is the short label shown on the row, `human` the preview."""
    now = time.time() if now is None else now
    t = " ".join(re.sub(r"\bat\s+", " ", (text or "").lower()).split())
    if not t:
        return {"ok": False, "human": "add a trigger, e.g. daily 08:00, every 2h, on wake"}
    m = re.fullmatch(r"on (wake|clap|connect)", t)
    if m:
        ev = m.group(1)
        return {"ok": True, "kind": "event", "chip": f"on {ev}", "human": f"→ every time you {'connect' if ev == 'connect' else ev}" if ev != "wake" else "→ every time FRIDAY wakes", "period": 0, "next": 0}
    m = re.fullmatch(r"every (\d+)\s*(m|min|mins|minutes|h|hr|hrs|hours)", t)
    if m:
        n = int(m.group(1))
        sec = n * (60 if m.group(2).startswith("m") else 3600)
        if sec < 300:
            return {"ok": False, "human": "the shortest interval is 5 minutes"}
        unit = "min" if m.group(2).startswith("m") else "h"
        return {"ok": True, "kind": "interval", "chip": f"every {n}{unit}", "human": f"→ every {n} {'minutes' if unit == 'min' else 'hours'}", "period": sec, "next": now + sec}
    m = re.fullmatch(r"(daily|weekdays|weekends|once|mon|tue|wed|thu|fri|sat|sun)\s+(\d{1,2})[:.](\d{2})", t)
    if m:
        what, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
        if hh > 23 or mm > 59:
            return {"ok": False, "human": "that is not a valid time"}
        days = {"daily": [], "weekdays": [0, 1, 2, 3, 4], "weekends": [5, 6], "once": []}.get(what)
        if days is None:
            days = [DAY_NAMES.index(what)]
        nxt = next_alarm(hh, mm, days, now)
        clock = f"{hh:02d}:{mm:02d}"
        human = {
            "daily": f"→ every day at {clock}",
            "weekdays": f"→ every weekday at {clock}",
            "weekends": f"→ Saturdays and Sundays at {clock}",
            "once": f"→ once, {('today' if same_day(nxt, now) else 'tomorrow')} at {clock}",
        }.get(what, f"→ every {what.capitalize()} at {clock}")
        period = 0 if what == "once" else (86400 if what == "daily" else 7 * 86400 if what in DAY_NAMES else 86400)
        return {"ok": True, "kind": "once" if what == "once" else "cron", "chip": f"{what} {clock}", "human": human, "period": period, "next": nxt, "days": days, "hour": hh, "minute": mm}
    return {"ok": False, "human": "try: daily 08:00 · weekdays 18:30 · every 2h · on wake · once 14:30"}


def advance_trigger(trig: dict, now: float | None = None) -> float:
    now = time.time() if now is None else now
    kind = trig.get("kind")
    if kind == "interval":
        return now + float(trig.get("period") or 3600)
    if kind == "cron":
        return next_alarm(int(trig.get("hour", 8)), int(trig.get("minute", 0)), list(trig.get("days") or []), now + 1)
    return 0.0
