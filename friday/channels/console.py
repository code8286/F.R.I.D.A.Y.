# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Terminal channel: a trusted local channel for running and debugging the headless core.

Type a message to talk to FRIDAY. When an approval is pending, your next line answers it:
    yes / y        approve a T2 action          <4-digit code>   approve a T3 action
    no  / n        deny
Commands:  /pending  /kill  /reset  /audit  /help  /exit
"""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any

from ..core.daemon import FridayCore
from ..security.tiers import ConfirmChannel

HELP = __doc__


class ConsoleChannel:
    def __init__(self, core: FridayCore, stdin: Any = None, out: Any = None):
        self.core = core
        self._stdin = stdin or sys.stdin
        self._out = out or sys.stdout
        self._lines: asyncio.Queue[str | None] = asyncio.Queue()
        self._tasks: set[asyncio.Task[Any]] = set()

    def _print(self, text: str = "") -> None:
        print(text, file=self._out, flush=True)

    # ---- stdin reader thread (daemon, so Ctrl-C / exit never hangs on input()) ----
    def _start_reader(self, loop: asyncio.AbstractEventLoop) -> None:
        def pump() -> None:
            while True:
                line = self._stdin.readline()
                if line == "":
                    loop.call_soon_threadsafe(self._lines.put_nowait, None)
                    return
                loop.call_soon_threadsafe(self._lines.put_nowait, line.rstrip("\r\n"))

        threading.Thread(target=pump, name="friday-console-stdin", daemon=True).start()

    # ---- presenters ----
    async def _present_confirmations(self) -> None:
        sub = self.core.bus.subscribe("confirm.requested")
        try:
            async for ev in sub:
                p = ev.payload
                self._print("")
                self._print("=" * 64)
                self._print(p["card"])
                if p["tier"] >= 3:
                    self._print(f"T3 action: type the code {p['short_code']} to approve, or 'no' to deny.")
                else:
                    self._print("Approve? yes / no")
                self._print(f"(expires in {p['ttl_s']:.0f}s)")
                self._print("=" * 64)
        finally:
            sub.close()

    async def _present_events(self) -> None:
        sub = self.core.bus.subscribe("core.warning")
        try:
            async for ev in sub:
                self._print(f"[warning] {ev.payload.get('message')}")
        finally:
            sub.close()

    # ---- input handling ----
    async def _turn(self, text: str) -> None:
        try:
            result = await self.core.submit(text, "console")
            self._print(f"friday> {result.text}")
            if result.status != "ok":
                self._print(f"[turn ended: {result.status}]")
        except Exception as exc:  # the REPL must survive anything
            self._print(f"[error] {type(exc).__name__}: {exc}")

    def _answer_pending(self, line: str) -> bool:
        pending = self.core.broker.pending()
        if not pending:
            return False
        req = pending[0]
        word = line.strip().lower()
        approve = word not in ("no", "n", "deny", "cancel", "")
        res = self.core.respond_confirmation(req.id, approve, ConfirmChannel.TYPED, principal="console", text=line)
        self._print(f"[approval {req.id}] {'ok: ' + res.reason if res.ok else 'refused: ' + res.reason}")
        return True

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._start_reader(loop)
        bg = [asyncio.create_task(self._present_confirmations()), asyncio.create_task(self._present_events())]
        self._print("FRIDAY online. Type /help for commands.")
        try:
            while True:
                line = await self._lines.get()
                if line is None or line.strip() in ("/exit", "/quit"):
                    break
                if not line.strip():
                    continue
                if await self._command(line.strip()):
                    continue
                if self._answer_pending(line):
                    continue
                task = asyncio.create_task(self._turn(line))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        finally:
            if self._tasks and not self.core.kill.tripped:  # let in-flight turns finish (briefly) on EOF/exit
                await asyncio.wait(list(self._tasks), timeout=5)
            for t in [*bg, *self._tasks]:
                t.cancel()
            await asyncio.gather(*bg, *self._tasks, return_exceptions=True)

    async def _command(self, line: str) -> bool:
        if not line.startswith("/"):
            return False
        cmd = line.split()[0].lower()
        if cmd == "/help":
            self._print(HELP or "")
        elif cmd == "/kill":
            self.core.trip_kill("console /kill", "console")
            self._print("[kill switch engaged]")
        elif cmd == "/reset":
            self.core.reset_kill("console")
            self._print("[kill switch reset]")
        elif cmd == "/pending":
            for r in self.core.broker.pending():
                self._print(f"{r.id}  {r.tool}  T{int(r.tier)}")
            self._print("(no more)")
        elif cmd == "/audit":
            res = self.core.audit.verify()
            self._print(f"audit: {'OK' if res.ok else 'FAILED - ' + str(res.error)} ({res.records} records)")
            for rec in self.core.audit.tail(8):
                self._print(f"  #{rec.seq} {rec.actor}:{rec.event}")
        else:
            self._print(f"unknown command {cmd}; /help")
        return True
