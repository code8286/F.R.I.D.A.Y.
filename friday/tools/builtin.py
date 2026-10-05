# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Built-in tools available in tranche 1 (so the headless core is demonstrable end to end).

The real tool groups (tasks, notes, alarms, fs, shell, web, ...) arrive in tranche 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..core.config import Config
from ..security.tiers import RiskTier
from .registry import ToolContext, ToolRegistry


def register_builtin(registry: ToolRegistry, cfg: Config) -> None:
    from ..brain.context_builder import _tz

    tz = _tz(cfg.conversation.timezone)

    @registry.tool(
        name="get_time",
        description="Get the current local date and time. Use when the user asks what time or date it is.",
        schema={"type": "object", "properties": {}},
        tier=RiskTier.T0,
    )
    def get_time(ctx: ToolContext) -> str:
        return datetime.now(tz).strftime("%A, %d %B %Y, %H:%M:%S %Z")

    @registry.tool(
        name="list_tools",
        description="List the names of every tool FRIDAY currently has. Use when the user asks what you can do.",
        schema={"type": "object", "properties": {}},
        tier=RiskTier.T0,
    )
    def list_tools(ctx: ToolContext) -> Any:
        return registry.names()
