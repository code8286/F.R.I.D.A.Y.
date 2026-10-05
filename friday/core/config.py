# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Configuration: TOML file + environment overrides + safe defaults.

Resolution order for the config file:
    1. ``--config`` CLI argument
    2. ``$FRIDAY_CONFIG``
    3. ``<data_dir>/config.toml``      (written with defaults on first run)

Environment overrides (win over the file):
    FRIDAY_DATA_DIR, FRIDAY_PROVIDER_URL

Memory is built in (``[memory]``). A leftover ``[hermes]`` section from older configs is ignored with a note.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        from . import _toml_min as tomllib  # type: ignore[no-redef]  # stdlib-only subset parser

from .errors import ConfigError


def default_data_dir() -> Path:
    override = os.environ.get("FRIDAY_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "friday"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "friday"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "friday"


@dataclass
class ProviderConfig:
    kind: str = "echo"                 # "friday" | "echo"  (echo = offline smoke-test provider)
    base_url: str = "http://localhost:20128"   # your local OmniRoute gateway
    path: str = "/v1/chat/completions" # request path appended to base_url
    model: str = "auto/best-reasoning" # must exist on the gateway (create a combo named "friday" to use model = "friday")
    codec: str = "openai"              # "openai" (chat/completions) | "messages" (block-based) | "text" (flattened prompt + JSON protocol)
    tool_mode: str = "auto"            # "auto" | "native" | "json"
    auth_scheme: str = "bearer"        # "bearer" | "header" | "query" | "none"
    auth_header: str = "Authorization" # for scheme "header"
    auth_prefix: str = ""              # prefix for scheme "header" (bearer always uses "Bearer ")
    auth_query_param: str = "key"      # for scheme "query"
    secret_name: str = "friday_api_key"
    response_text_path: str = "text"   # dotted path for the "text" codec's reply
    timeout_s: float = 120.0           # reasoning models can think for a while
    max_tokens: int = 4096             # reasoning tokens count against this on thinking models
    protocol_repair_attempts: int = 1


@dataclass
class MemoryConfig:
    enabled: bool = True
    use_model: bool = True             # LLM-assisted extraction + summaries (costs tokens); False = heuristics only
    auto_extract: bool = True          # pick up durable facts from your own messages after clean turns (model-assisted if use_model, else simple patterns)
    extract_min_chars: int = 40        # skip extraction for very short messages
    recall_k: int = 6                  # memories injected per turn
    recall_max_chars: int = 3000       # budget for the recalled-memory block
    max_fact_chars: int = 500
    summary_max_chars: int = 1500      # rolling summary of conversation that scrolled out of the context window
    restore_turns: int = 6             # recent exchanges restored into the session after a restart
    turn_log_retention_days: int = 90
    max_memories: int = 5000           # soft cap; lowest-value unpinned memories are pruned


@dataclass
class AgentConfig:
    max_iterations: int = 8            # LLM calls per turn
    max_tool_calls_per_turn: int = 16
    turn_timeout_s: float = 300.0
    tool_timeout_s: float = 60.0
    max_history_tokens: int = 24000    # rough estimate (chars/4)
    keep_min_turns: int = 2
    tool_output_max_chars: int = 12000
    summarize_untrusted_over_chars: int = 4000
    llm_retries: int = 3
    llm_backoff_base_s: float = 1.0
    llm_backoff_max_s: float = 20.0
    max_args_bytes: int = 65536


@dataclass
class SecurityConfig:
    confirm_ttl_s: float = 60.0
    max_pending_approvals: int = 8
    global_rate_per_min: int = 120
    workspace_dir: str = ""            # default: <data_dir>/workspace
    extra_denylist: list[str] = field(default_factory=list)   # extra glob patterns that always need T3
    allowed_telegram_ids: list[int] = field(default_factory=list)
    voice_t2_requires_readback: bool = True
    voice_t3_requires_challenge: bool = True  # loosen at your own risk (see Architecture §6)
    allow_private_net: bool = False    # NEVER enable unless you know why (SSRF)


@dataclass
class ConversationConfig:
    user_name: str = "Alpha"
    timezone: str = "Asia/Kolkata"


@dataclass
class Config:
    data_dir: Path = field(default_factory=default_data_dir)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    conversation: ConversationConfig = field(default_factory=ConversationConfig)
    config_path: Path | None = None
    notes: list[str] = field(default_factory=list)   # non-fatal load notices (shown at startup)

    # ---- derived paths ----
    @property
    def db_path(self) -> Path:
        return self.data_dir / "friday.db"

    @property
    def ws_token_path(self) -> Path:
        return self.data_dir / "ws_token"

    @property
    def workspace(self) -> Path:
        return Path(self.security.workspace_dir).expanduser() if self.security.workspace_dir else self.data_dir / "workspace"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


# --------------------------------------------------------------------------- loading
_SECTIONS = {
    "provider": ProviderConfig,
    "memory": MemoryConfig,
    "agent": AgentConfig,
    "security": SecurityConfig,
    "conversation": ConversationConfig,
}


def _apply(obj: Any, data: dict[str, Any], where: str) -> None:
    known = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            raise ConfigError(f"unknown config key [{where}] {key!r}")
        current = getattr(obj, key)
        if isinstance(current, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"[{where}] {key} must be true/false")
        elif isinstance(current, (int, float)) and not isinstance(current, bool):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"[{where}] {key} must be a number")
            value = type(current)(value)
        elif isinstance(current, str):
            if not isinstance(value, str):
                raise ConfigError(f"[{where}] {key} must be a string")
        elif isinstance(current, list):
            if not isinstance(value, list):
                raise ConfigError(f"[{where}] {key} must be a list")
        setattr(obj, key, value)


_LEGACY_SECTIONS = {"hermes"}   # dropped 2026-10-05: memory is native now

_VALID = {
    ("provider", "kind"): {"friday", "echo"},
    ("provider", "codec"): {"openai", "messages", "text"},
    ("provider", "tool_mode"): {"auto", "native", "json"},
    ("provider", "auth_scheme"): {"bearer", "header", "query", "none"},
}


def _validate(cfg: Config) -> None:
    for (section, key), allowed in _VALID.items():
        val = getattr(getattr(cfg, section), key)
        if val not in allowed:
            raise ConfigError(f"[{section}] {key} must be one of {sorted(allowed)}, got {val!r}")
    if cfg.agent.max_iterations < 1 or cfg.agent.max_tool_calls_per_turn < 1:
        raise ConfigError("[agent] iteration/tool-call caps must be >= 1")
    if cfg.security.confirm_ttl_s <= 0:
        raise ConfigError("[security] confirm_ttl_s must be > 0")
    m = cfg.memory
    if m.recall_k < 0 or m.max_fact_chars < 20 or m.summary_max_chars < 100 or m.restore_turns < 0 or m.max_memories < 10:
        raise ConfigError("[memory] values out of range")
    if cfg.provider.kind == "friday" and not cfg.provider.base_url:
        raise ConfigError("[provider] kind='friday' requires base_url")


def load_config(path: str | os.PathLike[str] | None = None, *, write_default: bool = True) -> Config:
    cfg = Config()
    explicit = path or os.environ.get("FRIDAY_CONFIG")
    cfg_path = Path(explicit).expanduser() if explicit else cfg.data_dir / "config.toml"

    if cfg_path.exists():
        try:
            raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read config {cfg_path}: {exc}") from exc
    else:
        # First run: write the documented default file AND apply exactly what it says, so the first run behaves
        # the same as every later run (the file's values differ from the bare dataclass defaults).
        raw = tomllib.loads(DEFAULT_CONFIG_TOML)
        if write_default and not explicit:
            try:
                cfg.data_dir.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
            except OSError:
                pass  # read-only home etc.; the defaults still apply
    if "data_dir" in raw:
        cfg.data_dir = Path(str(raw.pop("data_dir"))).expanduser()
    for name, value in raw.items():
        if name in _LEGACY_SECTIONS:
            cfg.notes.append(f"[{name}] in config.toml is no longer used (memory is built in); ignoring it")
            continue
        if name not in _SECTIONS:
            raise ConfigError(f"unknown config section [{name}]")
        if not isinstance(value, dict):
            raise ConfigError(f"[{name}] must be a table")
        _apply(getattr(cfg, name), value, name)

    cfg.config_path = cfg_path

    # environment overrides
    if os.environ.get("FRIDAY_DATA_DIR"):
        cfg.data_dir = Path(os.environ["FRIDAY_DATA_DIR"]).expanduser()
    if os.environ.get("FRIDAY_PROVIDER_URL"):
        cfg.provider.base_url = os.environ["FRIDAY_PROVIDER_URL"]

    _validate(cfg)
    return cfg


DEFAULT_CONFIG_TOML = '''\
# F.R.I.D.A.Y. configuration (written on first run; config.example.toml in the repo is identical).
# Restart FRIDAY after editing. Secrets never go here: use `friday set-secret <name>`.

[provider]
kind        = "echo"                    # "echo" = offline; "friday" = use the gateway below
base_url    = "http://localhost:20128"  # local OmniRoute gateway (its dashboard is /home; the API is under /v1)
path        = "/v1/chat/completions"
model       = "auto/best-reasoning"     # or "friday" after you create a combo with that name in OmniRoute
codec       = "openai"                  # "openai" | "messages" | "text"
tool_mode   = "auto"                    # "auto" | "native" | "json" (the gateway supports native tool calls)
auth_scheme = "bearer"                  # "bearer" | "header" | "query" | "none"
secret_name = "friday_api_key"          # keyring entry holding the key: friday set-secret friday_api_key
timeout_s   = 120                       # per model call; reasoning models can think for a while
max_tokens  = 4096                      # reasoning tokens count against this

[memory]                                # built-in long-term memory + context window (no external service)
enabled       = true
use_model     = true                    # model-assisted summaries + fact extraction; false = offline patterns only
auto_extract  = true                    # learn durable facts/preferences from your own messages
recall_k      = 6                       # memories injected per turn
restore_turns = 6                       # recent exchanges restored after a restart

[security]
confirm_ttl_s               = 60        # seconds an approval request stays valid
allowed_telegram_ids        = []        # your numeric Telegram user id(s); everyone else is ignored
voice_t3_requires_challenge = true      # keep true: a spoken "yes" never approves a T3 action

[conversation]
user_name = "Alpha"
timezone  = "Asia/Kolkata"
'''
