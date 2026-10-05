# FRIDAY v2 — Tranche 1 build log

**Status (2026-10-05, revision 3):** Tranche 1 (core + security skeleton + built-in memory + OmniRoute provider) is built, tested (189 tests, stdlib only; green on Python 3.10 (device), 3.11, 3.12, 3.13, also under `-W error::ResourceWarning`) and delivered to `Projects/F.R.I.D.A.Y/friday-v2/` on Alpha's machine. It runs headless: `python -m friday run`.

**Direction note:** this supersedes the older "he implements it himself / don't generate code" line in `friday_project_memory.md`. Current roles: Claude delivers the code in tranches (see `Architecture`), Alpha orchestrates, reverse-engineers and improves.

## Revision 2 — Hermes dropped (2026-10-05)

Alpha decided to forget Hermes entirely. FRIDAY now has its own auto-updating memory and context window inside the program.

- **Removed:** `friday/hermes/`, `[hermes]` config + `FRIDAY_HERMES_CLI`. A leftover `[hermes]` section in an existing `config.toml` is tolerated and ignored with a `[note]` at startup (no error), so nothing breaks if the old cli_path edit is still there.
- **Added:** `friday/memory/store.py` (SQLite: `memories`, `summaries`, `turns`; FTS5 porter/bm25 search with LIKE fallback; migration v2), `friday/memory/engine.py`, `friday/tools/memory_tools.py`, `[memory]` config block, CLI `python -m friday memory list|search|add|forget|pin|unpin|summary`.
- **Context window:** turns trimmed on whole-turn boundaries are folded into a per-session rolling summary (model-written when `use_model`, else a digest); the summary is recalled every turn. New loop hooks: `on_trim(session, dropped)`, `on_turn_done(session, turn, text, result)`.
- **Recall:** pinned first, then relevance (bm25) + importance + recency; injected as `<recalled_data>` in the turn's first user message only (never system prompt, never stored in history), within `recall_max_chars`; cached per turn.
- **Auto-update:** after a clean, successful turn, durable facts are extracted from the user's own message only (model-assisted if `use_model`, background task drained on stop; otherwise conservative patterns such as "remember that…", "I prefer…", "my X is…"). Dedupe on normalised text.
- **Restart continuity:** turn log restores the last `restore_turns` clean exchanges into the session.
- **Poisoning guard:** `memory_remember` is T1 so a tainted turn forces confirmation (stored as `approved`); `memory_forget` is T2; secrets refused via the Redactor; tainted turns contribute only user words to summary/turn log and are never restored; all memory writes audited.
- **Fixed on the way:** `Database.open()` leaked the connection when migration failed (newer schema).
- Tests: 144 → 179 (`tests/test_memory.py`: store, ranking, dedupe, FTS/LIKE, engine, summaries, restore, poisoning guard, restart, forget confirmation, overflow → summary, disabled memory).

## Revision 3 — provider pinned from probe_tests (2026-10-05)

- **Finding:** the "friday" endpoint is a local OmniRoute gateway at `http://localhost:20128`. `POST /home` returns the dashboard HTML (not an API). The real API is OpenAI-style `POST /v1/chat/completions` with `Authorization: Bearer <key>`, native `tool_calls` (arguments as a JSON string), SSE streaming with keepalive chunks, `GET /v1/models`. The bare model name `friday` is rejected (400 "Unable to determine provider for model"); `auto/best-reasoning` works (served by gemini-3.7-flash-*, reasoning model: 195 of 202 completion tokens were reasoning). Note: this contradicts the earlier memory note "not OpenAI-compatible".
- **Added:** `openai` codec (system message, assistant `tool_calls`, `role:"tool"` results, `[error]` prefix for failed tools, content-part replies, embedded `error` objects, `finish_reason:"length"` → truncated even with empty content, invalid argument JSON → rejected call instead of empty args); defaults changed to `codec="openai"`, `path="/v1/chat/completions"`, `timeout_s=120`, `max_tokens=4096`, `turn_timeout_s=300`; larger token budgets for summariser / memory calls (reasoning models); `python -m friday check-provider`; clearer provider-error text (shows the gateway's message).
- **Fixed:** a missing API key raised a bare `KeyError` that could escape the turn; it is now a typed `ProviderAuthError` pointing at `set-secret`.
- **Not tested live:** the probe outputs are captured as golden test fixtures, but the gateway is only reachable from Alpha's machine, so run `python -m friday check-provider` there.
- **Telegram:** FRIDAY gets its own NEW bot token (BotFather); Hermes stays independent with its own bot, so no 409 polling conflict.
- Tests: 179 → 189.

## Delivered (all of tranche 1)

- `core/`: config (TOML, `[memory]`), SQLite WAL + migrations, event bus, hash-chained audit log (optional HMAC key + tail anchor), kill switch, JSON-schema validator, sessions (turn-boundary trim, taint tracking), agent loop, daemon (`FridayCore`).
- `security/`: tiers T0-T3, taint + data envelopes, fs denylist (resolves symlinks/`..`), SSRF guard, secrets + redaction, rate limiter, policy engine, confirmation broker (args-hash binding, single use, 60 s TTL, per-tier channel rules, voice challenge phrase, HMAC'd Telegram callbacks, flood cap), code-built cards.
- `brain/`: canonical messages, `LLMProvider`, `FridayProvider` (pluggable `AuthStrategy` + codec, stdlib transport, auto fallback to strict JSON tool protocol), context builder with recall hook, quarantined summarizer.
- `memory/`: store + engine (above). `tools/`: registry, builtin `get_time`/`list_tools`, memory tools. `channels/console.py`; CLI (`run`, `init`, `set-secret`, `delete-secret`, `verify-audit`, `show-config`, `memory`).

## Decisions made (veto-able)

- Recalled memory is enveloped as data but does NOT taint a turn; untrusted tool output does, and taint lasts while that content is inside the history window (not just the current turn).
- Voice T3 approval needs the on-screen challenge phrase (never spoken by TTS); typed T3 approval needs the 4-digit code; any channel can deny.
- Provider wire format is now confirmed (OpenAI chat/completions via OmniRoute); `messages` and `text` codecs are kept as fallbacks.
- Fallback stdlib TOML parser (`_toml_min.py`) so config loads on Python 3.10 without `tomli`.
- Memory defaults: `use_model = true` (summaries/extraction cost a few tokens per turn); set false for fully offline operation. The echo provider never uses the model for memory.
- Pinned memories are set by you only (CLI), never by the model, so the model can't grow always-injected context.

## Open items / needed for later tranches

- **Provider:** run `python -m friday check-provider` on Alpha's machine (gateway is local). Optionally create a combo named `friday` in OmniRoute.
- **Telegram (tranche 5):** new bot via BotFather; need Alpha's numeric Telegram user ID then. Token goes in the keyring.
- Windows-specific code (owner-only ACL via `icacls`, keyring/Credential Manager, path normalisation) is untested; run the suite on Windows.
- Tools (tranche 2) must act on `PathVerdict.resolved`, delete via recycle bin + undo journal, and pin web fetches to `net_guard` IPs.
- Minor: a restored turn may also be present in the rolling summary if it was folded in before shutdown (harmless).

## Next

Tranche 2: tasks, notes, alarms + scheduler, filesystem, shell, web tools. Then sensors/voice, UI, integrations (calendar, news, GitHub, Telegram), packaging.