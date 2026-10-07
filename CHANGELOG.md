# Changelog

All notable changes to F.R.I.D.A.Y. are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Each architecture tranche
(see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), section 9) ships as a minor version
while the project is pre-1.0.

## [Unreleased]

Nothing yet. Next: tranche 4 (the desktop UI).

## [0.3.0] - 2026-10-06

Tranche 3: sensors and voice. **Off by default** (`[voice] enabled = false`): nothing listens to the microphone until
you opt in. The core is still standard library only; voice libraries are the optional `voice` extra and are imported
lazily, so FRIDAY runs without them and says what is missing.

### Added
- **Audio hub** (`friday.sensors.audio_hub`): the single owner of the microphone (16 kHz mono, 20 ms frames), with
  reconnect on failure or stall and a fallback from a silent default device to the loudest real input.
- **Double-clap detector**, ported from `jarvis.py` (adaptive noise floor, retrigger arming, gap window) without the
  once-per-process limit or hardcoded actions; claps must be short, so speech does not trigger it.
- **Wake phrase** "FRIDAY wake up" with Vosk (grammar restricted to the wake and stop phrases), on its own thread; **stop
  phrases** ("stop", "friday stop") cut speech off. **Activation fusion**: `either`, `both`, `clap` or `wake`, debounced.
- **Voice activity detection** (energy endpointer with pre-roll) and **local speech-to-text** with faster-whisper
  (model loaded from a local folder only; silence hallucinations dropped; falls back to the CPU if the GPU stack is broken).
- **Text-to-speech**: ElevenLabs over stdlib HTTPS (key from the OS keyring, voice id in config), falling back to the system
  voice (Windows SAPI, macOS `say`, Linux `espeak-ng`); a WAV cache for short fixed phrases only.
- **Voice channel** (`friday.channels.voice`): a listening window opened by the clap or wake phrase (FRIDAY greets, then
  listens; nothing is launched), half-duplex recording with barge-in, spoken replies (redacted, markdown, code and links
  removed, long replies cut to a sentence), spoken reminders, and a kill switch that silences everything.
- **Spoken approvals** with code-built readbacks (`render_readback` / `build_readback`): see Security below.
- CLI: `friday audio-devices`, `friday voice-check [--seconds N] [--say TEXT]`, `friday fetch-models [vosk|whisper|all] [--force]`.
- Config: a `[voice]` section; `pyproject.toml` gets the `voice` extra.
- Console: shows what was heard and prints the T3 challenge phrase for you to say (never spoken).
- 158 new tests (446 in total) using fakes for the microphone, engines, clock and network.

### Security
- Only approvals raised by a turn that arrived **by voice** (recorded as the approval's `origin`) can be answered by voice;
  a request from a typed or scheduled turn is never read out and never voice-answerable, even with a window open.
- T2 by voice needs a complete readback of the exact action, spoken word for word and played to the end, then a short clean
  "yes" that began after the readback ended. An action that cannot be read in full (over four arguments, long values, nested
  options) can only be approved on screen, and the broker enforces that too. T3 needs the on-screen challenge phrase.
- The recorder is off while FRIDAY speaks and for a guard afterwards; claps and the wake phrase are ignored then (a clap or
  "stop" while speaking only stops the speech).
- The running core never downloads models. `friday fetch-models` is https only, size and time capped, refuses redirects to
  http, supports a SHA-256 pin, unpacks safely, installs atomically, and `--force` never deletes outside the models folder.
- Spoken text is redacted before it reaches a TTS provider; audio is not stored or logged; the ElevenLabs request goes to a
  fixed host with no redirects and its response is capped and checked for plausible length.
- Found by an independent pre-release review and fixed here: voice ownership of approvals, truncated or rewritten readbacks,
  an engine crash escaping into a turn, a deaf channel after one bad frame, a half-installed model counting as installed,
  steady noise re-triggering the recorder forever, and a few smaller items.

### Notes
- The cloud build and its tests have no microphone, speakers, Vosk, Whisper or ElevenLabs access, so the real-hardware paths
  are covered by fakes only. Run `friday voice-check` after installing, and see `docs/DEPLOYMENT.md`, section 7.

## [0.2.0] - 2026-10-06

Tranche 2: local tools. Everything below sits behind the existing risk tiers, taint tracking and
confirmation broker, and each group can be switched off under `[tools]` in `config.toml`.
Still standard library only.

### Added
- **Tasks, notes and reminders** (`friday.personal`): SQLite-backed, with Markdown export for notes.
  Reminders are driven by a persistent asyncio scheduler that survives restarts, marks reminders it
  missed while the core was down as late, and repeats hourly, daily, on weekdays or weekly. A firing
  reminder is announced on the bus and the console and written to the audit log. It never reaches the
  model. Tools: `task_add/list/update/delete`, `note_add/list/search/read/update/delete/export`,
  `reminder_set/list/cancel/snooze`.
- **Filesystem tools**: `fs_list`, `fs_read`, `fs_search`, `fs_write`, `fs_edit`, `fs_move`,
  `fs_delete`, `fs_trash_list`, `fs_undo`. Deletes go to a trash folder in the data directory
  (purged after `trash_retention_days`, default 30), and every change is recorded in a signed undo journal.
- **Shell tool** `shell_run`: argv only (no shell), scrubbed environment, timeout, output cap and
  process-tree kill. A short read-only allowlist is T2; anything else is T3.
- **Web fetcher** `web_fetch` (T2): the connection is pinned to the IP the SSRF guard checked, TLS is
  verified against the host name, every redirect hop is validated, and size and time are capped. HTML is
  reduced to text and returned as untrusted data.
- CLI: `friday show tasks|notes|reminders|trash`, read-only and independent of the daemon.
- Config: a `[tools]` section, and `security.fs_roots` (default `["~"]`, the whole user profile).
  Writes outside the roots are T3.
- A live-context line listing open tasks.

### Changed
- Tools act only on the paths the policy engine resolved and classified (`ToolContext.resolved_paths`),
  so a path cannot change between approval and execution.
- Tool output can set its own summarisation threshold (`summarize_over`), and a tool can declare that
  its errors are untrusted (`errors_untrusted`, used by `web_fetch`).
- The policy engine checks URLs syntactically before approval and does no DNS lookup. Name resolution
  happens once, at fetch time, in the pinned connection.

### Security
- Critical locations (drive roots, the home folder, FRIDAY's own folders and anything that contains
  one) can never be deleted or moved. The request is denied before any approval card is shown.
- Paths are rejected before touching the disk when they are UNC, device, alternate-data-stream or
  reserved-name paths. Risky suffixes (scripts, shortcuts, launchers) and persistence locations
  (startup folders, shell profiles) are judged on the resolved path and need T3. Containment checks are
  case-insensitive.
- Rows written on a tainted turn (tasks, notes, reminders) are marked and later returned to the model as
  untrusted data, so stored text cannot become an instruction.
- The SSRF guard now judges IPv4 addresses hidden inside IPv6 (compatible, NAT64, SIIT, Teredo, 6to4)
  and blocks site-local addresses.
- Shell: batch files are refused, and a bare program name that resolves inside the working folder is
  refused.
- An independent adversarial review of this tranche produced fixes and a regression test for each
  finding (`tests/test_review_fixes.py`).

### Fixed
- Reminder scheduling from a worker thread could stall the loop. It now hands off with
  `call_soon_threadsafe`.

### Known limits
- Worker threads cannot be cancelled. Background children started by a shell command survive a normal exit.
  ACLs and extended attributes are not preserved when a file is rewritten. The home folder is readable by
  default; narrow `security.fs_roots` if that is too wide. The Windows-specific code is exercised by CI
  but has had less manual testing than the Linux paths.

### Tests
- 288 tests (94 new), on Python 3.10 to 3.13.

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
[0.3.0]: #030---2026-10-06
[0.2.0]: #020---2026-10-06
[0.1.1]: #011---2026-10-06
[0.1.0]: #010---2026-10-05
