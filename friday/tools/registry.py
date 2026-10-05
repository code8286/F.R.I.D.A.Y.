# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Tool registry: every tool declares a JSON schema, a risk tier and a taint policy (Architecture §5)."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import ToolArgumentError, UnknownToolError
from ..core.schema import check_schema, validate
from ..security.taint import Trust
from ..security.tiers import RiskTier

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass
class ToolContext:
    """What a handler may know about the call. Handlers never receive secrets or the raw model output."""

    session_id: str
    turn_id: str
    source: str                 # "console" | "ui" | "voice" | "telegram" ...
    tainted: bool = False
    services: Any = None        # FridayCore (db, bus, config, ...) — set by the loop


@dataclass
class ToolOutput:
    text: str
    untrusted: bool | None = None   # None -> use spec.output_trust
    source: str | None = None       # provenance label for the envelope, e.g. "web:example.com"
    meta: dict[str, Any] = field(default_factory=dict)


Classifier = Callable[[dict[str, Any]], "tuple[RiskTier, str] | None"]


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[..., Any]
    tier: RiskTier = RiskTier.T0
    side_effecting: bool | None = None          # default: tier >= T1
    output_trust: Trust = Trust.TRUSTED         # UNTRUSTED -> enveloped + taints the turn
    summarize_output: bool = False              # large untrusted blobs go through the quarantined summarizer
    timeout_s: float | None = None
    path_params: tuple[str, ...] = ()
    path_op: str = "read"
    path_param_ops: Mapping[str, str] = field(default_factory=dict)
    url_params: tuple[str, ...] = ()
    rate_limit_per_min: int = 0
    classifier: Classifier | None = None        # may only ESCALATE the tier
    touches_credentials: bool = False           # forces T3

    @property
    def is_side_effecting(self) -> bool:
        return self.side_effecting if self.side_effecting is not None else self.tier >= RiskTier.T1


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    # ---- registration ----
    def register(self, spec: ToolSpec) -> ToolSpec:
        if not NAME_RE.match(spec.name):
            raise ValueError(f"invalid tool name {spec.name!r} (use lower_snake_case, <=64 chars)")
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} already registered")
        if not spec.description.strip():
            raise ValueError(f"tool {spec.name!r} needs a description (it tells the model when to call it)")
        schema = dict(spec.schema)
        schema.setdefault("type", "object")
        if schema["type"] != "object":
            raise ValueError(f"tool {spec.name!r}: top-level schema must be an object")
        schema.setdefault("properties", {})
        schema.setdefault("additionalProperties", False)
        check_schema(schema)
        for p in (*spec.path_params, *spec.url_params):
            if p not in schema["properties"]:
                raise ValueError(f"tool {spec.name!r}: path/url param {p!r} not in schema")
        for p in spec.path_param_ops:
            if p not in spec.path_params:
                raise ValueError(f"tool {spec.name!r}: path_param_ops names non-path param {p!r}")
        spec.schema = schema
        self._tools[spec.name] = spec
        return spec

    def tool(self, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator form: ``@registry.tool(name=..., description=..., schema=..., tier=...)``."""

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register(ToolSpec(handler=fn, **kwargs))
            return fn

        return deco

    # ---- lookup ----
    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(f"unknown tool {name!r}") from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def llm_schemas(self) -> list[dict[str, Any]]:
        return [
            {"name": s.name, "description": s.description, "input_schema": s.schema}
            for s in (self._tools[n] for n in self.names())
        ]

    # ---- validation + invocation ----
    @staticmethod
    def validate_args(spec: ToolSpec, args: Any, max_bytes: int = 65536) -> dict[str, Any]:
        if not isinstance(args, dict):
            raise ToolArgumentError("arguments must be a JSON object")
        try:
            size = len(json.dumps(args, default=str).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ToolArgumentError(f"arguments are not JSON-serialisable: {exc}") from exc
        if size > max_bytes:
            raise ToolArgumentError(f"arguments too large ({size} bytes, limit {max_bytes})")
        errors = validate(args, spec.schema)
        if errors:
            raise ToolArgumentError("invalid arguments: " + "; ".join(errors[:6]))
        return args

    @staticmethod
    async def invoke(spec: ToolSpec, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        handler = spec.handler
        if inspect.iscoroutinefunction(handler):
            result = await handler(ctx, **args)
        else:
            result = await asyncio.to_thread(handler, ctx, **args)
            if inspect.isawaitable(result):  # sync wrapper returning a coroutine
                result = await result
        return _coerce_output(result)


def _coerce_output(result: Any) -> ToolOutput:
    if isinstance(result, ToolOutput):
        return result
    if result is None:
        return ToolOutput("ok")
    if isinstance(result, str):
        return ToolOutput(result)
    try:
        return ToolOutput(json.dumps(result, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return ToolOutput(str(result))
