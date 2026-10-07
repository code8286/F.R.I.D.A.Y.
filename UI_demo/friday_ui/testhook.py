# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Scripted UI runs for screenshot checks (development only):  python run.py --script-file steps.json

steps.json is a list of steps, run in order:
  {"wait": 800}                      wait N ms
  {"key": "4"} / {"key": "Escape"}   press a key on the window
  {"click": [x, y]}                  left click at window coordinates
  {"action": ["todo.toggle", {...}]} send a core action
  {"dev": "clap"}                    a demo control
  {"shot": "out.png"}                save a screenshot
  {"quit": true}
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest

KEYS = {"Escape": Qt.Key.Key_Escape, "Space": Qt.Key.Key_Space, "Tab": Qt.Key.Key_Tab, "Return": Qt.Key.Key_Return,
        "Left": Qt.Key.Key_Left, "Right": Qt.Key.Key_Right, "Up": Qt.Key.Key_Up, "Down": Qt.Key.Key_Down, "F1": Qt.Key.Key_F1}


def run_script(app: Any, win: Any, bridge: Any, core: Any, path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        steps = json.load(fh)
    it = iter(steps)

    def nxt() -> None:
        try:
            st = next(it)
        except StopIteration:
            app.quit()
            return
        delay = 0
        if "wait" in st:
            delay = int(st["wait"])
        elif "key" in st:
            k = st["key"]
            mods = Qt.KeyboardModifier.ControlModifier if st.get("ctrl") else Qt.KeyboardModifier.NoModifier
            if k in KEYS:
                QTest.keyClick(win, KEYS[k], mods)
            else:
                QTest.keyClick(win, k, mods)
            delay = 30
        elif "click" in st:
            x, y = st["click"]
            QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x), int(y)))
            delay = 30
        elif "type" in st:
            for ch in st["type"]:
                QTest.keyClick(win, ch)
            delay = 30
        elif "action" in st:
            name, args = st["action"]
            bridge.action(name, args)
        elif "dev" in st:
            bridge.dev(st["dev"], st.get("args", {}))
        elif "shot" in st:
            win.grabWindow().save(st["shot"])
        elif st.get("quit"):
            app.quit()
            return
        QTimer.singleShot(delay, nxt)

    QTimer.singleShot(300, nxt)
