# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""friday-core: the headless asyncio daemon that owns all state (Architecture §1).

`FridayCore` wires every component together. Channels (console now; UI WebSocket, voice and Telegram
later) only call `submit()`, `respond_confirmation()` and `trip_kill()`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..brain.context_builder import ContextBuilder, _tz
from ..brain.provider import EchoProvider, FridayProvider, LLMProvider, build_auth
from ..brain.summarizer import QuarantinedSummarizer
from ..memory.engine import MemoryEngine
from ..memory.store import MemoryStore
from ..personal.scheduler import Scheduler
from ..personal.store import ReminderStore
from ..security.confirm_broker import ConfirmationBroker, RespondResult
from ..security.fs_rules import FsRules
from ..security.policy import PolicyEngine
from ..security.ratelimit import RateLimiter
from ..security.secrets import Redactor, SecretStore, ensure_token_file
from ..security.tiers import ConfirmChannel
from ..tools.builtin import register_builtin
from ..tools.fs_tools import FsJournal, register_fs_tools
from ..tools.memory_tools import register_memory_tools
from ..tools.personal_tools import register_personal_tools
from ..tools.registry import ToolRegistry
from ..tools.shell_tool import register_shell_tool
from ..tools.web_tools import register_web_tools
from .agent_loop import AgentLoop, TurnResult
from .audit import AuditLog
from .bus import EventBus
from .config import Config
from .db import Database
from .killswitch import KillSwitch
from .session import SessionManager

log = logging.getLogger("friday.core")


class FridayCore:
    def __init__(
        self,
        cfg: Config,
        *,
        provider: LLMProvider | None = None,
        secrets: SecretStore | None = None,
        registry: ToolRegistry | None = None,
    ):
        self.cfg = cfg
        self.bus = EventBus()
        self.redactor = Redactor()
        self.secrets = secrets or SecretStore(redactor=self.redactor)
        self.secrets.redactor = self.redactor
        self.db = Database(cfg.db_path)
        self.audit = AuditLog(self.db, redact=self.redactor.obj)
        self.kill = KillSwitch(self.bus, self.audit)
        self.registry = registry or ToolRegistry()
        self.degraded: list[str] = []
        self.ws_token: str = ""
        self.scheduler: Scheduler | None = None
        self.fs_journal: FsJournal | None = None
        self.personal: dict[str, Any] = {}
        self.voice: Any = None          # friday.channels.voice.VoiceChannel when [voice] enabled = true (tranche 3)

        data_dir = cfg.data_dir
        self.fs = FsRules(
            cfg.workspace,
            protected_roots=[data_dir, Path(__file__).resolve().parents[1]],   # data + the installed code

            extra_patterns=cfg.security.extra_denylist,
            roots=cfg.security.fs_roots,
        )
        self.policy = PolicyEngine(cfg.security, self.fs, self.kill, RateLimiter())
        self.broker = ConfirmationBroker(self.bus, self.audit, cfg.security, redact=self.redactor.text)
        self.context = ContextBuilder(cfg, recall_max_chars=cfg.memory.recall_max_chars)
        self.sessions = SessionManager(cfg.security, self.audit)

        self.provider: LLMProvider = provider or self._build_provider()
        self.summarizer = QuarantinedSummarizer(self.provider)

        # Built-in memory + context window (no external service). Model-assisted work is skipped for the echo provider.
        self.memory: MemoryEngine | None = None
        if cfg.memory.enabled:
            self.memory = MemoryEngine(
                MemoryStore(self.db), cfg.memory, provider=self.provider,
                use_model=cfg.memory.use_model and self.provider.name != "echo",
                redact=self.redactor.text, audit=self.audit, halted=lambda: self.kill.tripped,
            )
            self.context.set_recall(self.memory.recall_for_turn)
        self.loop = AgentLoop(
            provider=self.provider,
            registry=self.registry,
            policy=self.policy,
            broker=self.broker,
            audit=self.audit,
            bus=self.bus,
            context=self.context,
            kill=self.kill,
            redactor=self.redactor,
            cfg=cfg.agent,
            services=self,
            summarizer=self.summarizer,
            on_trim=self.memory.on_trim if self.memory else None,
            on_turn_done=self.memory.on_turn_done if self.memory else None,
        )
        if registry is None:
            register_builtin(self.registry, cfg)
            if self.memory:
                register_memory_tools(self.registry, self.memory)
            self._register_local_tools()
        self._started = False
        if cfg.voice.enabled:
            self._setup_voice()

    def _setup_voice(self) -> None:
        """Build the microphone/speech stack. Anything missing (library, model, key, device) is reported and skipped; it never stops the core."""
        from ..sensors.stack import build_voice  # imported lazily: the audio stack is optional and only needed when enabled

        try:
            self.voice, notes = build_voice(self)
        except Exception as exc:  # noqa: BLE001 - a broken audio setup must not take the core down
            log.error("voice setup failed: %s: %s", type(exc).__name__, exc)
            self.degraded.append(f"voice: setup failed ({type(exc).__name__}: {exc})")
            return
        self.degraded.extend(notes)

    async def start_voice(self) -> str:
        """Turn voice chat on while running (the console's /voice, or `friday run --voice`). Returns a one-line status."""
        if self.voice is not None:
            return "voice is already on"
        before = len(self.degraded)
        self._setup_voice()
        if self.voice is None:
            return "voice could not start: " + ("; ".join(self.degraded[before:]) or "see the log")
        await self.voice.start()
        notes = self.degraded[before:]
        self.audit.append("core", "voice.enabled_on_demand", {})
        return "voice is on" + (" (" + "; ".join(notes) + ")" if notes else "")

    async def stop_voice(self) -> str:
        if self.voice is None:
            return "voice is already off"
        await self.voice.stop()
        self.voice = None
        self.audit.append("core", "voice.disabled_on_demand", {})
        return "voice is off"

    def _register_local_tools(self) -> None:
        """Tranche 2 tools. Each group can be switched off in [tools]; a switched-off group has no tools at all."""
        t = self.cfg.tools
        if t.reminders:
            self.scheduler = Scheduler(ReminderStore(self.db), self.bus, self.audit, _tz(self.cfg.conversation.timezone))
        if t.tasks or t.notes or t.reminders:
            self.personal = register_personal_tools(
                self.registry, self.cfg, self.db, self.scheduler, tasks=t.tasks, notes=t.notes, reminders=t.reminders
            )
            if t.tasks:
                store = self.personal["tasks"]

                def tasks_line() -> str | None:
                    open_n, overdue = store.counts()
                    if not open_n:
                        return None
                    return f"{open_n} open" + (f", {overdue} overdue" if overdue else "")

                self.context.add_live_source("Open tasks", tasks_line)
        if t.fs:
            self.fs_journal = register_fs_tools(self.registry, self.cfg, self.db, self.fs)
        if t.shell:
            register_shell_tool(self.registry, self.cfg)
        if t.web:
            register_web_tools(self.registry, self.cfg)

    # ------------------------------------------------------------------ provider
    def _build_provider(self) -> LLMProvider:
        pc = self.cfg.provider
        if pc.kind == "echo":
            return EchoProvider()
        return FridayProvider(pc, build_auth(pc, self.secrets))

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._started:
            return
        self.bus.bind_loop()
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.workspace.mkdir(parents=True, exist_ok=True)
        self.db.open()

        # Audit key policy: keyed chain if (and only if) a persistent key exists for this install.
        keyed_flag = self.db.kv_get("audit.keyed")
        key = self.secrets.audit_hmac_key(create=keyed_flag is None)
        if keyed_flag is None:
            self.db.kv_set("audit.keyed", "1" if key else "0", 0.0)
        elif keyed_flag == "0":
            key = None
        self.audit._key = key
        res = self.audit.verify()
        if not res.ok:
            msg = f"audit log verification FAILED: {res.error}"
            log.error(msg)
            self.degraded.append(msg)
            self.bus.publish("core.warning", {"message": msg})
        if keyed_flag == "1" and key is None:
            self.degraded.append("audit HMAC key is missing from the keyring")

        if self.memory:
            info = self.memory.start(self.sessions.main())
            if not info["fts"]:
                self.degraded.append("memory search is using the slow LIKE fallback (SQLite built without FTS5)")

        if self.fs_journal is not None:
            try:
                purged = self.fs_journal.purge(self.cfg.tools.trash_retention_days)
                if purged:
                    self.audit.append("core", "trash.purged", {"items": purged, "older_than_days": self.cfg.tools.trash_retention_days})
            except OSError as exc:
                log.warning("trash purge failed: %s", exc)
        if self.scheduler is not None:
            self.scheduler.start()
        if self.voice is not None:
            await self.voice.start()

        self.ws_token = ensure_token_file(self.cfg.ws_token_path)
        self.redactor.add(self.ws_token)
        self.audit.append("core", "core.started", {"version": _version(), "provider": self.provider.name, "degraded": self.degraded})
        self._started = True
        self.bus.publish("core.started", {"degraded": list(self.degraded)})

    async def stop(self) -> None:
        if not self._started:
            return
        self.broker.cancel_all("shutdown")
        if self.voice is not None:
            await self.voice.stop()
        if self.scheduler is not None:
            await self.scheduler.stop()
        if self.memory:
            await self.memory.drain()
        self.audit.append("core", "core.stopped", {})
        self.bus.publish("core.stopped", {})
        self.db.close()
        self._started = False

    # ------------------------------------------------------------------ channel-facing API
    async def submit(
        self, text: str, channel: str = "console", principal: int | str | None = None, *, voice_session_active: bool = False
    ) -> TurnResult:
        origin = self.sessions.admit(channel, principal, voice_session_active=voice_session_active)
        return await self.loop.run_turn(self.sessions.main(), text, origin)

    def respond_confirmation(
        self,
        request_id: str,
        approve: bool,
        channel: ConfirmChannel,
        **kw: Any,
    ) -> RespondResult:
        return self.broker.respond(request_id, approve, channel, **kw)

    def trip_kill(self, reason: str = "manual", source: str = "unknown") -> None:
        self.kill.trip(reason, source)

    def reset_kill(self, principal: str = "user") -> None:
        self.kill.reset(principal)


def _version() -> str:
    from .. import __version__

    return __version__
