# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Policy engine — turns (tool, arguments, taint state) into a gate decision, entirely in code.

No prompt is a security boundary; this is. Order of evaluation:
  1. kill switch            -> DENY
  2. rate limits            -> DENY
  3. static tier + dynamic classifier (escalate only) + credential flag
  4. filesystem rules for path params, SSRF rules for url params (hard DENY on bad URLs)
  5. taint: a tainted turn forces CONFIRM for every side-effecting tool, whatever its tier
  6. tier -> gate (T0/T1 auto, T2/T3 confirm)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..core.config import SecurityConfig
from ..core.killswitch import KillSwitch
from . import net_guard
from .fs_rules import FsRules
from .ratelimit import RateLimiter
from .tiers import ConfirmChannel, Gate, RiskTier

if TYPE_CHECKING:  # avoid an import cycle with tools.registry
    from ..tools.registry import ToolSpec

ALL_CHANNELS = frozenset(ConfirmChannel)


@dataclass(frozen=True)
class Decision:
    gate: Gate
    tier: RiskTier
    reasons: tuple[str, ...] = ()
    allowed_channels: frozenset[ConfirmChannel] = ALL_CHANNELS
    resolved_paths: tuple[str, ...] = ()
    denied_reason: str | None = None


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str)]
    return []


class PolicyEngine:
    def __init__(
        self,
        cfg: SecurityConfig,
        fs: FsRules,
        kill: KillSwitch,
        rates: RateLimiter | None = None,
        resolver: Any = None,
    ):
        self.cfg = cfg
        self.fs = fs
        self.kill = kill
        self.rates = rates or RateLimiter()
        self._resolver = resolver

    def evaluate(self, spec: ToolSpec, args: dict[str, Any], *, tainted: bool) -> Decision:
        if self.kill.tripped:
            return Decision(Gate.DENY, RiskTier.T3, ("kill switch engaged",), frozenset(), denied_reason="kill switch engaged")

        if not self.rates.allow("*", self.cfg.global_rate_per_min):
            return self._deny("global rate limit exceeded")
        if spec.rate_limit_per_min and not self.rates.allow(f"tool:{spec.name}", spec.rate_limit_per_min):
            return self._deny(f"rate limit for {spec.name} exceeded")

        tier = spec.tier
        reasons: list[str] = []
        resolved: list[str] = []

        if spec.touches_credentials:
            tier = max(tier, RiskTier.T3)
            reasons.append("touches credentials or settings")

        if spec.classifier is not None:
            try:
                dyn = spec.classifier(args)
            except Exception as exc:  # a broken classifier fails closed
                tier = max(tier, RiskTier.T3)
                reasons.append(f"classifier error ({type(exc).__name__}); treating as T3")
            else:
                if dyn is not None:
                    dyn_tier, why = dyn
                    if dyn_tier > tier:
                        tier = dyn_tier
                    reasons.append(why)

        for param in spec.path_params:
            op = spec.path_param_ops.get(param, spec.path_op)
            for raw in _as_list(args.get(param)):
                try:
                    verdict = self.fs.classify(raw, op)
                except ValueError as exc:
                    return self._deny(f"bad path in {param!r}: {exc}")
                resolved.append(str(verdict.resolved))
                if verdict.tier > tier:
                    tier = verdict.tier
                reasons.extend(r for r in verdict.reasons if r not in reasons)

        for param in spec.url_params:
            for raw in _as_list(args.get(param)):
                v = net_guard.check_url(raw, resolver=self._resolver, allow_private=self.cfg.allow_private_net)
                if not v.ok:
                    return self._deny(f"blocked URL in {param!r}: {v.reason}")

        gate = Gate.AUTO
        if tier >= RiskTier.T2:
            gate = Gate.CONFIRM
        if tainted and (spec.is_side_effecting or tier >= RiskTier.T1):
            reasons.append("this turn contains untrusted content")
            if gate is Gate.AUTO:
                tier = max(tier, RiskTier.T2)  # tainted confirmations use T2 channels (never weaker)
            gate = Gate.CONFIRM

        return Decision(
            gate=gate,
            tier=tier,
            reasons=tuple(reasons),
            allowed_channels=ALL_CHANNELS,
            resolved_paths=tuple(resolved),
        )

    @staticmethod
    def _deny(reason: str) -> Decision:
        return Decision(Gate.DENY, RiskTier.T3, (reason,), frozenset(), denied_reason=reason)
