# Changelog

All notable changes to F.R.I.D.A.Y. are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Each architecture tranche
(see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), section 9) ships as a minor version
while the project is pre-1.0.

## [Unreleased]

### Planned (tranche 2, local tools)
- Tasks and notes (SQLite, Markdown export), alarms and reminders with a persistent asyncio scheduler.
- Filesystem tools that act on the resolved path, delete through the recycle bin with an undo journal.
- Shell tool (no `shell=True`, timeout, output cap) and a web fetcher that pins requests to the IPs
  checked by the SSRF guard.

## [0.1.1] - 2026-10-06

### Fixed
- `friday set-secret` and `delete-secret` crashed with a raw `RuntimeError` traceback on a machine
  without the optional `keyring` package (first seen on Windows). They now stop with a one-screen
  `error:` message that gives the exact `pip install keyring` command for the running interpreter and
  the environment-variable alternative. The new `SecretStoreUnavailable` error is also raised when the
  OS keyring exists but refuses the write. The key is never written to disk as a fallback.

### Changed
- `docs/DEPLOYMENT.md`, `README.md` and `SECURITY.md` state that storing the API key requires `keyring`,
  including when running from source with `python -m friday`.

### Tests
- 194 tests (3 new): the read-only environment backend and its error text, environment reads, and a CLI test that
  checks `set-secret` prints an error, not a traceback, and exits with status 1.

## [0.1.0] - 2026-10-05

Tranche 1: the headless core, the security model, built-in memory and the model provider.
Runs on the Python standard library alone (3.10 to 3.13).

### Added
- **Core daemon** (`friday.core`): TOML configuration with validation, SQLite (WAL) storage with
  versioned migrations, an in-process event bus, a thread-safe kill switch, a JSON-schema validator,
  sessions with turn-boundary trimming, and `FridayCore`, the single API every channel uses
  (`submit`, `respond_confirmation`, `trip_kill`, `reset_kill`).
- **Agent loop**: runs every tool call in a reply and answers each one, retries transient model
  errors with backoff (honouring `Retry-After`), caps iterations, tool calls and wall-clock time per
  turn, and repairs history after a kill, timeout or error so tool calls and results always stay paired.
- **Security model** (`friday.security`):
  - Risk tiers T0 to T3 mapped to gates (auto, confirm, deny), decided in code by the policy engine:
    kill switch, global and per-tool rate limits, escalate-only classifiers, filesystem rules for path
    arguments, an SSRF guard for URL arguments.
  - Taint tracking: untrusted tool output is wrapped in a data envelope and forces confirmation of
    every side-effecting tool while it remains in the context window.
  - Confirmation broker: approval bound to a hash of the exact tool and arguments, single use, 60 s
    expiry, per-tier channel rules (click, typed `yes` or 4-digit code, HMAC-signed Telegram button,
    voice readback, and an on-screen challenge phrase for voice T3), a cap on pending approvals, and
    approval cards built by code from sanitised arguments.
  - Secrets live in the OS keyring (read-only `FRIDAY_SECRET_*` environment fallback) and are redacted
    from tool output, logs, memory and the audit trail.
  - Append-only, hash-chained audit log (SQLite triggers block updates and deletes), optionally keyed
    with an HMAC key from the keyring, with tail anchoring and a `verify-audit` command.
  - Quarantined summariser: large untrusted text goes through a tool-less model call first.
- **Model provider** (`friday.brain`): `LLMProvider` interface and `FridayProvider` with pluggable
  authentication (bearer, header, query, none) and wire codecs:
  - `openai`: OpenAI-style `POST /v1/chat/completions`, verified against the local OmniRoute gateway
    (`http://localhost:20128`, Bearer key, native `tool_calls`).
  - `messages` (block-based) and `text` (flattened prompt) as fallbacks.
  - Automatic fallback to a strict JSON tool-call protocol when an endpoint rejects native tools.
  - `EchoProvider` for offline use and `ScriptedProvider` for tests.
- **Built-in memory and context window** (`friday.memory`):
  - Long-term memories (facts, preferences, episodes) with FTS5 search (porter stemming, bm25), a
    LIKE fallback, deduplication, importance, pinning and provenance (`user`, `assistant`, `approved`).
  - Recall each turn by relevance, importance and recency, injected as a `<recalled_data>` envelope,
    never into the system prompt.
  - Turns trimmed out of the context window are folded into a rolling per-session summary.
  - Durable facts are extracted from the user's own messages after clean turns (model-assisted, or
    pattern-based when `use_model = false`).
  - The last clean exchanges are restored after a restart.
  - Memory tools: `memory_search` (T0), `memory_remember` (T1), `memory_forget` (T2).
- **Tools**: tool registry (schema, tier, taint policy, path and URL parameters, rate limits) and the
  built-in tools `get_time` and `list_tools`.
- **Console channel** with approvals, `/pending`, `/kill`, `/reset`, `/audit`.
- **CLI** (`friday` or `python -m friday`): `run`, `init`, `show-config`, `set-secret`,
  `delete-secret`, `verify-audit`, `check-provider` (live endpoint test that never prints the key),
  `memory list|search|add|forget|pin|unpin|summary`, `--version`.
- Minimal TOML parser fallback so configuration loads on Python 3.10 without `tomli`.
- Packaging: `pyproject.toml` (installable wheel, `friday` console script, optional `keyring` extra),
  Apache-2.0 `LICENSE` and `NOTICE`, SPDX headers on every source file, `SECURITY.md`,
  `CONTRIBUTING.md`, `docs/DEPLOYMENT.md`, CI workflow (Ubuntu and Windows, Python 3.10 to 3.13), ruff
  configuration.
- 191 unit and integration tests (stdlib `unittest`).

### Changed
- The architecture moved from an external Hermes memory bridge to memory built into FRIDAY;
  delivery tranches after tranche 2 moved up by one (see `docs/ARCHITECTURE.md`, revision 2).
- Provider defaults now match the confirmed gateway: `codec = "openai"`,
  `path = "/v1/chat/completions"`, `base_url = "http://localhost:20128"`,
  `model = "auto/best-reasoning"`, `timeout_s = 120`, `max_tokens = 4096` (reasoning tokens count
  against it), `turn_timeout_s = 300`.
- Telegram will use FRIDAY's own new bot token; Hermes keeps its own bot, so the two don't compete
  for updates.
- Bad-request errors from the model endpoint now show the endpoint's message.
- `config.example.toml` is now byte-identical to the file written on first run (enforced by a test).
- Distribution name is `friday-assistant`; the import name and command stay `friday`.

### Removed
- The Hermes bridge (`friday/hermes`), the `[hermes]` config section and `FRIDAY_HERMES_CLI`. A
  leftover `[hermes]` section is ignored with a note instead of failing.

### Fixed
- On the very first run the default `config.toml` was written but not applied, so the first run used
  different settings from every later run.
- A missing API key raised a bare `KeyError` that could escape the turn; it is now a typed
  authentication error pointing at `friday set-secret`.
- `Database.open()` leaked its connection when a migration failed (for example, a newer schema).
- Python 3.10 and 3.11 reported an unretrieved task exception when the kill switch cancelled a turn.
- Tool-call arguments that are not valid JSON are rejected back to the model instead of running the
  tool with empty arguments.

### Security
- No prompt is treated as a security boundary: tiers, taint, confirmation, filesystem and network
  rules are enforced in code. See `SECURITY.md` for the threat model and known limits.

[Unreleased]: #unreleased
[0.1.1]: #011---2026-10-06
[0.1.0]: #010---2026-10-05
