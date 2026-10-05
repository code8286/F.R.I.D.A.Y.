# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""LLM provider layer (Architecture §3).

`LLMProvider` is the only interface the agent loop knows. `FridayProvider` talks to your endpoint (a local
OmniRoute gateway: OpenAI-style ``POST /v1/chat/completions`` with a Bearer key): authentication is a
pluggable `AuthStrategy`, the request/response shape is a pluggable *codec* (``openai`` | ``messages`` |
``text``), and if the endpoint has no native tool use it falls back to the strict JSON tool-call protocol
(see json_protocol.py).

Transport is stdlib `urllib` run in a worker thread: no third-party HTTP dependency in a 24x7 daemon.
"""

from __future__ import annotations

import asyncio
import json
import socket
import urllib.error
import urllib.request
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..core.config import ProviderConfig
from ..core.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderConnectionError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderServerError,
    ProviderTimeout,
)
from ..security.secrets import SecretStore
from . import json_protocol
from .messages import (
    Block,
    LLMResponse,
    Message,
    TextBlock,
    ToolUseBlock,
    Usage,
    assistant_text,
    block_from_dict,
    message_to_dict,
    user_text,
)


class LLMProvider(ABC):
    name = "provider"

    @abstractmethod
    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[Mapping[str, Any]],
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """One model call. Raises a typed `ProviderError` subclass on failure."""


# ---------------------------------------------------------------------------- auth strategies
class AuthStrategy(ABC):
    @abstractmethod
    def apply(self, headers: dict[str, str], url: str) -> str:
        """Mutate `headers` and/or return a modified URL."""


class NoAuth(AuthStrategy):
    def apply(self, headers: dict[str, str], url: str) -> str:
        return url


class BearerAuth(AuthStrategy):
    def __init__(self, token_fn: Callable[[], str]):
        self._token = token_fn

    def apply(self, headers: dict[str, str], url: str) -> str:
        headers["Authorization"] = f"Bearer {self._token()}"
        return url


class HeaderAuth(AuthStrategy):
    def __init__(self, header: str, prefix: str, token_fn: Callable[[], str]):
        self._header, self._prefix, self._token = header, prefix, token_fn

    def apply(self, headers: dict[str, str], url: str) -> str:
        headers[self._header] = f"{self._prefix}{self._token()}"
        return url


class QueryAuth(AuthStrategy):
    def __init__(self, param: str, token_fn: Callable[[], str]):
        self._param, self._token = param, token_fn

    def apply(self, headers: dict[str, str], url: str) -> str:
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True) + [(self._param, self._token())]
        return urlunsplit(parts._replace(query=urlencode(query)))


def build_auth(cfg: ProviderConfig, secrets: SecretStore) -> AuthStrategy:
    def token() -> str:
        try:
            return secrets.require(cfg.secret_name)
        except KeyError as exc:  # missing key must surface as a typed provider error, not crash the turn
            raise ProviderAuthError(f"API key {cfg.secret_name!r} is not set (python -m friday set-secret {cfg.secret_name})") from exc

    if cfg.auth_scheme == "none":
        return NoAuth()
    if cfg.auth_scheme == "bearer":
        return BearerAuth(token)
    if cfg.auth_scheme == "header":
        return HeaderAuth(cfg.auth_header, cfg.auth_prefix, token)
    return QueryAuth(cfg.auth_query_param, token)


# ---------------------------------------------------------------------------- transport
@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    async def post(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> HttpResponse: ...


class UrllibTransport:
    async def post(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> HttpResponse:
        return await asyncio.to_thread(self._post, url, headers, body, timeout)

    @staticmethod
    def _post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> HttpResponse:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (scheme checked by caller)
                return HttpResponse(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read() or b"")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise ProviderTimeout("request timed out") from exc
            raise ProviderConnectionError(f"cannot reach provider: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ProviderTimeout("request timed out") from exc
        except OSError as exc:
            raise ProviderConnectionError(f"network error: {exc}") from exc


def raise_for_status(resp: HttpResponse) -> None:
    s = resp.status
    if 200 <= s < 300:
        return
    detail = resp.body[:300].decode("utf-8", "replace")
    if s in (401, 403):
        raise ProviderAuthError(f"authentication rejected ({s})")
    if s == 408:
        raise ProviderTimeout("provider timed out (408)")
    if s == 429:
        try:
            retry = float(resp.headers.get("retry-after", ""))
        except ValueError:
            retry = None
        raise ProviderRateLimited("rate limited (429)", retry)
    if s >= 500:
        raise ProviderServerError(f"provider error {s}: {detail}")
    raise ProviderBadRequest(f"request rejected ({s}): {detail}")


# ---------------------------------------------------------------------------- FridayProvider
def _dig(data: Any, path: str) -> Any:
    cur = data
    for key in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(key)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


class FridayProvider(LLMProvider):
    name = "friday"

    def __init__(self, cfg: ProviderConfig, auth: AuthStrategy, transport: Transport | None = None):
        self.cfg = cfg
        self.auth = auth
        self.transport = transport or UrllibTransport()
        self._native_ok = True

    # ---- public ----
    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[Mapping[str, Any]],
        max_tokens: int | None = None,
    ) -> LLMResponse:
        max_tokens = max_tokens or self.cfg.max_tokens
        native = self._use_native(tools)
        try:
            return await self._once(system, messages, tools, native, max_tokens)
        except ProviderBadRequest as exc:
            if tools and native and self.cfg.tool_mode == "auto" and "tool" in str(exc).lower():
                self._native_ok = False  # endpoint rejected native tools: use the JSON protocol from now on
                return await self._once(system, messages, tools, False, max_tokens)
            raise

    # ---- internals ----
    def _use_native(self, tools: Sequence[Mapping[str, Any]]) -> bool:
        if not tools:
            return True
        if self.cfg.codec == "text" or self.cfg.tool_mode == "json":
            return False
        if self.cfg.tool_mode == "native":
            return True
        return self._native_ok

    async def _once(
        self, system: str, messages: Sequence[Message], tools: Sequence[Mapping[str, Any]], native: bool, max_tokens: int
    ) -> LLMResponse:
        if native or not tools:
            return await self._call(system, messages, tools if native else (), max_tokens, json_mode=False)

        tool_map = {t["name"]: t["input_schema"] for t in tools}
        sys_text = f"{system}\n\n{json_protocol.protocol_instructions(tools)}"
        msgs = list(messages)
        repairs = max(0, self.cfg.protocol_repair_attempts)
        for attempt in range(repairs + 1):
            raw = await self._call(sys_text, msgs, (), max_tokens, json_mode=True)
            try:
                blocks, stop = json_protocol.parse_reply(raw.text, tool_map)
            except ProviderProtocolError as exc:
                if attempt >= repairs:
                    raise
                msgs = msgs + [assistant_text(raw.text), user_text(json_protocol.repair_prompt(str(exc)))]
                continue
            return LLMResponse(blocks, stop, raw.usage)  # type: ignore[arg-type]
        raise ProviderProtocolError("unreachable")  # pragma: no cover

    async def _call(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[Mapping[str, Any]],
        max_tokens: int,
        *,
        json_mode: bool,
    ) -> LLMResponse:
        cfg = self.cfg
        if cfg.codec == "openai":
            wire = json_protocol.to_text_messages(messages) if json_mode else _to_openai_messages(messages)
            body: dict[str, Any] = {
                "model": cfg.model,
                "messages": [{"role": "system", "content": system}, *wire],
                "max_tokens": max_tokens,
            }
            if tools:
                body["tools"] = [
                    {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}}
                    for t in tools
                ]
        elif cfg.codec == "text":
            body = {
                "model": cfg.model,
                "system": system,
                "prompt": json_protocol.to_transcript(messages),
                "max_tokens": max_tokens,
            }
        else:
            wire = (
                json_protocol.to_text_messages(messages) if json_mode else [message_to_dict(m) for m in messages]
            )
            body = {"model": cfg.model, "system": system, "messages": wire, "max_tokens": max_tokens}
            if tools:
                body["tools"] = [dict(t) for t in tools]

        url = cfg.base_url.rstrip("/") + "/" + cfg.path.lstrip("/")
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "friday/0.1"}
        url = self.auth.apply(headers, url)
        resp = await self.transport.post(url, headers, json.dumps(body).encode("utf-8"), cfg.timeout_s)
        raise_for_status(resp)
        return self._decode(resp.body)

    def _decode(self, raw: bytes) -> LLMResponse:
        text_body = raw.decode("utf-8", "replace")
        try:
            data: Any = json.loads(text_body)
        except json.JSONDecodeError:
            if not text_body.strip():
                raise ProviderProtocolError("empty reply from provider") from None
            return LLMResponse([TextBlock(text_body.strip())])

        usage = Usage()
        if isinstance(data, dict) and isinstance(data.get("usage"), dict):
            u = data["usage"]
            usage = Usage(
                int(u.get("input_tokens", u.get("prompt_tokens", 0)) or 0),
                int(u.get("output_tokens", u.get("completion_tokens", 0)) or 0),
            )

        if self.cfg.codec == "openai":
            return _decode_openai(data, usage)

        if self.cfg.codec == "text":
            value = _dig(data, self.cfg.response_text_path)
            if not isinstance(value, str):
                raise ProviderProtocolError(f"no text at {self.cfg.response_text_path!r} in provider reply")
            return LLMResponse([TextBlock(value)], "end_turn", usage)

        blocks: list[Block] = []
        content = data.get("content") if isinstance(data, dict) else None
        if isinstance(content, str):
            blocks.append(TextBlock(content))
        elif isinstance(content, list):
            for item in content:
                try:
                    blocks.append(block_from_dict(item))
                except (KeyError, ValueError, TypeError) as exc:
                    raise ProviderProtocolError(f"unparseable content block: {exc}") from exc
        elif isinstance(data, dict):
            for key in ("text", "output", "response", "completion"):
                if isinstance(data.get(key), str):
                    blocks.append(TextBlock(data[key]))
                    break
        if not blocks:
            raise ProviderProtocolError("provider reply contained no usable content")
        stop: Any = "tool_use" if any(isinstance(b, ToolUseBlock) for b in blocks) else "end_turn"
        if isinstance(data, dict) and data.get("stop_reason") in ("max_tokens", "length") and stop != "tool_use":
            stop = "max_tokens"
        return LLMResponse(blocks, stop, usage)


# ---------------------------------------------------------------------------- OpenAI chat/completions codec
def _to_openai_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Canonical messages -> OpenAI chat messages (tool results become role="tool" messages)."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.text or None}
            uses = m.tool_uses()
            if uses:
                msg["tool_calls"] = [
                    {"id": u.id, "type": "function", "function": {"name": u.name, "arguments": json.dumps(u.arguments, ensure_ascii=False)}}
                    for u in uses
                ]
            elif not msg["content"]:
                msg["content"] = ""
            out.append(msg)
            continue
        for r in m.tool_results():
            out.append({"role": "tool", "tool_call_id": r.tool_use_id, "content": ("[error] " if r.is_error else "") + r.content})
        if m.text or not m.tool_results():
            out.append({"role": "user", "content": m.text})
    return out


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in (None, "text"))
    return ""


def _decode_openai(data: Any, usage: Usage) -> LLMResponse:
    if not isinstance(data, dict):
        raise ProviderProtocolError("provider reply is not a JSON object")
    if isinstance(data.get("error"), (dict, str)):
        err = data["error"]
        msg = err.get("message", "") if isinstance(err, dict) else err
        raise ProviderServerError(f"provider reported an error: {str(msg)[:200]}")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderProtocolError("provider reply has no choices")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    blocks: list[Block] = []
    text = _content_text(message.get("content")).strip()
    if text:
        blocks.append(TextBlock(text))
    for i, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") if isinstance(call, dict) else None
        if not isinstance(fn, dict) or not isinstance(fn.get("name"), str):
            raise ProviderProtocolError("malformed tool call in provider reply")
        raw_args = fn.get("arguments")
        if isinstance(raw_args, dict):
            args: Any = raw_args
        else:
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else {}
            except json.JSONDecodeError:
                args = None
        if not isinstance(args, dict):
            # Unparseable arguments must not run as "no arguments": the marker fails schema validation, so the
            # model is told its call was invalid and can retry.
            args = {"_invalid_arguments": str(raw_args)[:200]}
        blocks.append(ToolUseBlock(str(call.get("id") or f"call_{i}_{uuid.uuid4().hex[:6]}"), fn["name"], args))
    finish = choice.get("finish_reason")
    if any(isinstance(b, ToolUseBlock) for b in blocks):
        stop: Any = "tool_use"
    elif finish == "length":
        stop = "max_tokens"      # incl. thinking models that spent the whole budget reasoning (empty content)
    else:
        stop = "end_turn"
    return LLMResponse(blocks, stop, usage)


# ---------------------------------------------------------------------------- offline providers
class EchoProvider(LLMProvider):
    """Offline smoke-test provider. Plain text is echoed; ``!tool <name> {json}`` triggers a tool call."""

    name = "echo"

    async def complete(self, *, system, messages, tools, max_tokens=None) -> LLMResponse:  # type: ignore[override]
        last = messages[-1]
        results = last.tool_results()
        if results:
            joined = " | ".join(r.content[:200] for r in results)
            return LLMResponse([TextBlock(f"Tool results: {joined}")])
        text = last.text.strip()
        if text.startswith("!tool "):
            rest = text[6:].strip()
            name, _, raw = rest.partition(" ")
            try:
                args = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                return LLMResponse([TextBlock("Usage: !tool <name> {json arguments}")])
            return LLMResponse(
                [TextBlock(f"Calling {name}."), ToolUseBlock("echo_" + uuid.uuid4().hex[:8], name, args)],
                "tool_use",
            )
        return LLMResponse([TextBlock(f"(echo) You said: {text}")])


class ScriptedProvider(LLMProvider):
    """Deterministic provider for tests: pops one scripted item per call and records every request."""

    name = "scripted"

    def __init__(self, script: list[Any]):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, system, messages, tools, max_tokens=None) -> LLMResponse:  # type: ignore[override]
        self.calls.append({"system": system, "messages": [Message(m.role, list(m.blocks), dict(m.meta)) for m in messages], "tools": list(tools)})
        if not self.script:
            raise AssertionError("ScriptedProvider ran out of responses")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(self.calls[-1])
            if asyncio.iscoroutine(item):
                item = await item
        return item
