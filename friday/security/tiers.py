# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Risk tiers, gates and confirmation channels (Architecture §6)."""

from __future__ import annotations

from enum import Enum, IntEnum


class RiskTier(IntEnum):
    T0 = 0  # read-only, local, non-sensitive            -> auto
    T1 = 1  # reversible local writes in the workspace   -> auto (confirm if the turn is tainted)
    T2 = 2  # network, edits to existing files, sends     -> confirm (click / typed yes / voice yes + readback)
    T3 = 3  # destructive, state-changing shell, secrets  -> confirm (click / typed code / Telegram / voice + challenge)

    @property
    def label(self) -> str:
        return {0: "T0 read", 1: "T1 local write", 2: "T2 sensitive", 3: "T3 destructive"}[int(self)]


class Gate(str, Enum):
    AUTO = "auto"
    CONFIRM = "confirm"
    DENY = "deny"


class ConfirmChannel(str, Enum):
    UI_CLICK = "ui_click"
    TYPED = "typed"
    TELEGRAM_BUTTON = "telegram_button"
    VOICE = "voice"
