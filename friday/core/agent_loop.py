# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""The agent loop (Architecture §3, §6).

Carries over the fixes from the earlier design review:
  * executes ALL tool calls in a response and answers every one (even denied / killed / failed ones),
  * trims history only on turn boundaries, so tool_use / tool_result pairs are never split,
  * typed errors, one return type, retry with backoff for transient provider failures,
  * iteration cap + per-turn budget (LLM calls, tool calls, wall clock),
and enforces the security model: policy gate -> confirmation broker -> single-use approval bound to the
exact arguments -> redacted, enveloped, taint-tracked output.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from ..brain.context_builder import ContextBuilder
from ..brain.messages import (
    LLMResponse,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    assistant_text,
    user_text,
)
from ..brain.provider import LLMProvider
from ..brain.summarizer import QuarantinedSummarizer
from ..security.card import sanitize_display
from ..security.confirm_broker import ApprovalState, ConfirmationBroker
from ..security.policy import PolicyEngine
from ..security.secrets import Redactor
from ..security.taint import Trust, wrap
from ..security.tiers import Gate
from ..tools.registry import ToolContext, ToolRegistry
from .audit import AuditLog
from .bus import EventBus
from .config import AgentConfig
from .errors import (
    ConfirmationError,
    KillSwitchTripped,
    ProviderError,
    ProviderRateLimited,
    ToolArgumentError,
    ToolError,
    UnknownToolError,
)
from .killswitch import KillSwitch
from .session import Origin, Session, TurnContext

Status = Literal["ok", "iteration_cap", "killed", "timeout", "error"]


@dataclass
class TurnResult:
    status: Status
    text: str
    turn_id: str
    llm_calls: int
    tool_calls: int
    tainted: bool


@dataclass
class _Exec:
    block: ToolResultBlock
    untrusted: bool = False


class AgentLoop:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        registry: ToolRegistry,
        policy: PolicyEngine,
        broker: ConfirmationBroker,
        audit: AuditLog,
        bus: EventBus,
        context: ContextBuilder,
        kill: KillSwitch,
        redactor: Redactor,
        cfg: AgentConfig,
        services: Any = None,
        summarizer: QuarantinedSummarizer | None = None,
        on_trim: Callable[[Session, list[Message]], Awaitable[None]] | None = None,
        on_turn_done: Callable[[Session, TurnContext, str, TurnResult], Awaitable[None]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.provider = provider
        self.registry = registry
        self.policy = policy
        self.broker = broker
        self.audit = audit
        self.bus = bus
        self.context = context
        self.kill = kill
        self.redactor = redactor
        self.cfg = cfg
        self.services = services
        self.summarizer = summarizer
        self.on_trim = on_trim
        self.on_turn_done = on_turn_done
        self._sleep = sleep
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running: set[asyncio.Task[Any]] = set()
        kill.on_trip(self._kill_hook)

    # ------------------------------------------------------------------ kill switch plumbing
    def _kill_hook(self) -> None:
        """May be called from any thread (hotkey, Telegram worker)."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._on_kill)
        else:
            self._on_kill()

    def _on_kill(self) -> None:
        self.broker.cancel_all("kill switch")
        for task in list(self._running):
            task.cancel()

    # ------------------------------------------------------------------ public API
    async def run_turn(self, session: Session, text: str, origin: Origin) -> TurnResult:
        self._loop = asyncio.get_running_loop()
        async with session.lock:
            turn = TurnContext.new(session, origin.channel)
            try:
                result = await self._with_timeout(self._run(session, turn, text, origin))
            except asyncio.TimeoutError:
                self._seal(session, turn, "[Stopped: this turn took too long.]")
                result = self._result("timeout", "I ran out of time on that one. Try again or break it into smaller steps.", turn, session)
            except KillSwitchTripped:
                self._seal(session, turn, "[Stopped by the kill switch.]")
                result = self._result("killed", "Stopped. The kill switch is engaged.", turn, session)
            except asyncio.CancelledError:
                self._seal(session, turn, "[Stopped by the kill switch.]" if self.kill.tripped else "[Turn cancelled.]")
                if not self.kill.tripped:
                    raise  # genuine external cancellation: propagate
                result = self._result("killed", "Stopped. The kill switch is engaged.", turn, session)
            except ProviderError as exc:
                self._seal(session, turn, "[Stopped: the model could not be reached.]")
                self.audit.append("loop", "turn.provider_error", {"turn": turn.turn_id, "type": type(exc).__name__, "msg": str(exc)[:200]})
                result = self._result("error", self._provider_error_text(exc), turn, session)
            if self.on_turn_done is not None:
                try:
                    await self.on_turn_done(session, turn, text, result)
                except Exception:
                    pass  # memory bookkeeping must never fail a turn
            self.audit.append(
                "loop", "turn.finished",
                {"turn": turn.turn_id, "status": result.status, "llm_calls": turn.llm_calls, "tool_calls": turn.tool_calls},
            )
            self.bus.publish("turn.finished", {"turn": turn.turn_id, "status": result.status, "text": result.text})
            return result

    async def _with_timeout(self, coro: Awaitable[TurnResult]) -> TurnResult:
        """Run the turn as its own task with an explicit timeout.

        (asyncio.wait_for wraps the coroutine in an inner task on Python <= 3.11 and leaves its exception
        unretrieved when the kill switch cancels us; owning the task makes behaviour identical on 3.10-3.13.)
        The task is registered so the kill switch can cancel it from any thread.
        """
        inner = asyncio.ensure_future(coro)
        self._running.add(inner)
        try:
            done, _ = await asyncio.wait({inner}, timeout=self.cfg.turn_timeout_s)
            if not done:
                inner.cancel()
                await asyncio.gather(inner, return_exceptions=True)
                raise asyncio.TimeoutError
            return inner.result()
        except asyncio.CancelledError:
            inner.cancel()
            await asyncio.gather(inner, return_exceptions=True)
            raise
        finally:
            self._running.discard(inner)

    # ------------------------------------------------------------------ the loop
    async def _run(self, session: Session, turn: TurnContext, text: str, origin: Origin) -> TurnResult:
        self.kill.check()
        dropped = session.trim(self.cfg.max_history_tokens, self.cfg.keep_min_turns)
        if dropped and self.on_trim:
            try:
                await self.on_trim(session, dropped)
            except Exception:
                pass  # summarising what left the context window is best-effort

        turn.start_index = len(session.history)
        session.append(user_text(text, source=origin.channel, trust=Trust.TRUSTED.value))
        self.audit.append("loop", "turn.started", {"turn": turn.turn_id, "source": origin.channel, "chars": len(text)})
        self.bus.publish("turn.started", {"turn": turn.turn_id, "source": origin.channel})

        tools = self.registry.llm_schemas()
        for _ in range(self.cfg.max_iterations):
            self.kill.check()
            system, messages = await self.context.prepare(session, turn)
            resp = await self._call_llm(system, messages, tools)
            turn.llm_calls += 1
            turn.input_tokens += resp.usage.input_tokens
            turn.output_tokens += resp.usage.output_tokens

            blocks = list(resp.blocks) or [TextBlock("(no response)")]
            session.append(Message("assistant", blocks, {"stop_reason": resp.stop_reason}))
            uses = [b for b in blocks if isinstance(b, ToolUseBlock)]
            if not uses:
                final = "\n".join(b.text for b in blocks if isinstance(b, TextBlock)).strip()
                if resp.stop_reason == "max_tokens":
                    final += "\n[response truncated]"
                self.bus.publish("assistant.message", {"turn": turn.turn_id, "text": final})
                return self._result("ok", final or "(no response)", turn, session)

            results: list[ToolResultBlock] = []
            batch_tainted = False
            try:
                for tu in uses:
                    self.kill.check()
                    out = await self._execute(session, turn, tu, batch_tainted)
                    results.append(out.block)
                    batch_tainted = batch_tainted or out.untrusted
            except (KillSwitchTripped, asyncio.CancelledError):
                # Answer every outstanding tool_use so history stays valid, then bubble up.
                for tu in uses[len(results):]:
                    results.append(ToolResultBlock(tu.id, "Aborted: the kill switch was engaged.", True))
                session.append(Message("user", results, {"tool_results": True, "tainted": batch_tainted}))
                raise
            session.append(Message("user", results, {"tool_results": True, "tainted": batch_tainted}))

        self._seal(session, turn, "[Stopped: iteration limit reached.]")
        return self._result(
            "iteration_cap",
            "I hit my step limit for this request before finishing. Tell me to continue, or narrow it down.",
            turn, session,
        )

    # ------------------------------------------------------------------ LLM with retry
    async def _call_llm(self, system: str, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        attempt = 0
        while True:
            self.kill.check()
            try:
                return await self.provider.complete(system=system, messages=messages, tools=tools)
            except ProviderError as exc:
                if not exc.retryable or attempt >= self.cfg.llm_retries:
                    raise
                if isinstance(exc, ProviderRateLimited) and exc.retry_after:
                    delay = min(exc.retry_after, self.cfg.llm_backoff_max_s)
                else:
                    delay = min(self.cfg.llm_backoff_max_s, self.cfg.llm_backoff_base_s * (2 ** attempt))
                    delay += random.uniform(0, delay * 0.25)
                attempt += 1
                self.bus.publish("llm.retry", {"attempt": attempt, "delay": delay, "error": type(exc).__name__})
                await self._sleep(delay)

    @staticmethod
    def _provider_error_text(exc: ProviderError) -> str:
        return {
            "ProviderAuthError": "The model rejected my credentials. Check the API key (python -m friday set-secret friday_api_key).",
            "ProviderBadRequest": f"The model endpoint rejected my request: {sanitize_display(str(exc))[:200]}",
            "ProviderProtocolError": "The model replied in a format I couldn't understand.",
        }.get(type(exc).__name__, "I couldn't reach the model after several tries. I'll be fine once it's back.")

    # ------------------------------------------------------------------ one tool call
    async def _execute(self, session: Session, turn: TurnContext, tu: ToolUseBlock, batch_tainted: bool) -> _Exec:
        def fail(msg: str) -> _Exec:
            return _Exec(ToolResultBlock(tu.id, msg, True))

        turn.tool_calls += 1
        if turn.tool_calls > self.cfg.max_tool_calls_per_turn:
            return fail("Tool-call budget for this turn is exhausted. Summarise what you have for the user.")

        try:
            spec = self.registry.get(tu.name)
        except UnknownToolError:
            self.audit.append("loop", "tool.unknown", {"turn": turn.turn_id, "name": tu.name[:80]})
            return fail(f"Unknown tool {sanitize_display(tu.name)[:80]!r}. Use only the tools you were given.")

        try:
            args = self.registry.validate_args(spec, tu.arguments, self.cfg.max_args_bytes)
        except ToolArgumentError as exc:
            self.audit.append("loop", "tool.bad_args", {"turn": turn.turn_id, "tool": spec.name, "error": str(exc)[:200]})
            return fail(str(exc))

        tainted = session.is_tainted() or batch_tainted
        decision = self.policy.evaluate(spec, args, tainted=tainted)
        self.audit.append(
            "loop", "tool.requested",
            {
                "turn": turn.turn_id, "tool": spec.name, "tier": int(decision.tier), "gate": decision.gate.value,
                "reasons": list(decision.reasons), "tainted": tainted, "args": self.redactor.obj(_clip_args(args)),
            },
        )

        if decision.gate is Gate.DENY:
            return fail(f"DENIED by policy: {decision.denied_reason or 'not allowed'}. Do not retry; tell the user.")

        if decision.gate is Gate.CONFIRM:
            try:
                req = self.broker.create(session_id=session.id, tool=spec.name, args=args, decision=decision)
            except ConfirmationError as exc:
                return fail(f"Could not request approval: {exc}")
            state = await self.broker.wait(req)
            if state is not ApprovalState.APPROVED:
                why = {"denied": "The user declined this action.", "expired": "The approval request timed out.",
                       "cancelled": "The approval was cancelled."}.get(state.value, "The action was not approved.")
                return fail(f"NOT APPROVED: {why} Do not retry the same action; ask the user how to proceed.")
            try:
                self.broker.consume(req.id, spec.name, args)
            except ConfirmationError as exc:
                return fail(f"Approval could not be used: {exc}")
            self.kill.check()

        ctx = ToolContext(session.id, turn.turn_id, turn.source, tainted, self.services)
        timeout = spec.timeout_s or self.cfg.tool_timeout_s
        try:
            out = await asyncio.wait_for(self.registry.invoke(spec, ctx, args), timeout)
        except asyncio.TimeoutError:
            self.audit.append("loop", "tool.timeout", {"turn": turn.turn_id, "tool": spec.name})
            return fail(f"{spec.name} timed out after {timeout:.0f}s.")
        except ToolError as exc:
            self.audit.append("loop", "tool.failed", {"turn": turn.turn_id, "tool": spec.name, "error": self.redactor.text(str(exc))[:200]})
            return fail(self.redactor.text(str(exc))[:1000])
        except (KillSwitchTripped, asyncio.CancelledError):
            raise
        except Exception as exc:  # tool bug or environment error: report, never crash the loop
            msg = self.redactor.text(f"{type(exc).__name__}: {exc}")[:400]
            self.audit.append("loop", "tool.crashed", {"turn": turn.turn_id, "tool": spec.name, "error": msg})
            return fail(f"{spec.name} failed: {msg}")

        return await self._shape_output(turn, spec.name, spec.output_trust, spec.summarize_output, out, tu.id)

    async def _shape_output(self, turn: TurnContext, name: str, spec_trust: Trust, summarize: bool, out: Any, tool_use_id: str) -> _Exec:
        trust = spec_trust
        if out.untrusted is True:
            trust = Trust.UNTRUSTED
        elif out.untrusted is False and spec_trust is Trust.UNTRUSTED:
            trust = Trust.TRUSTED
        source = out.source or f"tool:{name}"

        text = self.redactor.text(out.text)
        if trust is Trust.UNTRUSTED and self.summarizer is not None and (
            summarize or len(text) > self.cfg.summarize_untrusted_over_chars
        ):
            text = self.redactor.text(await self.summarizer.summarize(text, source, purpose=f"result of {name}"))
            source = f"{source}+summarised"
        cap = self.cfg.tool_output_max_chars
        if len(text) > cap:
            text = text[:cap] + f"\n[truncated {len(text) - cap} chars]"

        self.audit.append("loop", "tool.finished", {"turn": turn.turn_id, "tool": name, "chars": len(text), "trust": trust.value})
        return _Exec(ToolResultBlock(tool_use_id, wrap(text, source, trust)), untrusted=trust.taints)

    # ------------------------------------------------------------------ history repair
    def _seal(self, session: Session, turn: TurnContext, marker: str) -> None:
        """After an abnormal exit make the history valid again: answer dangling tool_use, end on assistant."""
        h = session.history
        if len(h) <= turn.start_index:
            return
        last = h[-1]
        if last.role == "assistant" and last.tool_uses():
            h.append(Message("user", [ToolResultBlock(t.id, "Interrupted before this tool ran.", True) for t in last.tool_uses()], {"tool_results": True}))
        if h[-1].role == "user":
            h.append(assistant_text(marker, sealed=True))

    @staticmethod
    def _result(status: Status, text: str, turn: TurnContext, session: Session) -> TurnResult:
        return TurnResult(status, text, turn.turn_id, turn.llm_calls, turn.tool_calls, session.is_tainted())


def _clip_args(args: dict[str, Any], limit: int = 300) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > limit:
            out[k] = v[:limit] + f"…[{len(v)} chars]"
        else:
            out[k] = v
    return out
