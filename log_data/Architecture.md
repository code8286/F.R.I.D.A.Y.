# F.R.I.D.A.Y. v2: Architecture

This is the full architecture. Code follows in tranches, in the order at the bottom. Where I made a call that you can veto, I mark it **Decision**.

**Status:** tranche 1 is released as **0.1.0** (2026-10-05). See `CHANGELOG.md` for what shipped and `docs/DEPLOYMENT.md` to run it.

**Revision 2 (2026-10-05): Hermes is out.** FRIDAY no longer connects to Hermes for memory, sessions or context. It has its own auto-updating memory and context-window management built into the program (section 4). The Hermes bridge, its outbox and its tool group are gone, and the Telegram interface now talks to the Telegram Bot API directly (section 4.5).

**Revision 3 (2026-10-05): provider confirmed.** The model endpoint is the local OmniRoute gateway, which speaks OpenAI-style chat/completions with a Bearer key and native tool calls (section 3). FRIDAY gets its own Telegram bot; Hermes keeps its own (section 4.5).

## 1. Process model

FRIDAY runs as two processes under one launcher:

- **`friday-core`** is a headless asyncio daemon that runs 24x7. It owns all state, the scheduler, the sensors, the LLM loop, the memory engine and the policy engine.
- **`friday-ui`** is a PySide6 client for the HUD, control box and tray. It talks to the core over a local WebSocket on `127.0.0.1` with a random token stored in a user-only file.

**Decision:** I'm splitting them so a UI crash never kills your alarms or Telegram access. The launcher is a supervisor that restarts either process, and it registers for autostart at login.

```
 ┌─ Sensors ───────────────┐   ┌─ Channels ──────────────┐
 │ mic hub → clap detector │   │ Desktop UI (WebSocket)  │
 │         → wake phrase   │   │ Voice session (STT/TTS) │
 └────────┬────────────────┘   │ Telegram (Bot API)      │
          │ activate           └────────┬────────────────┘
          ▼                             ▼
   ┌──────────────── Session Manager (trust-tagged inputs) ───────────────┐
   │  Context Builder ← Memory Engine recall + live context + local state │
   │  Agent Loop  ⇄  LLM Provider ("friday")                              │
   │      │ tool calls                                                    │
   │      ▼                                                               │
   │  Policy Engine ─► Confirmation Broker ─► (UI card | voice | Telegram)│
   │      ▼                                                               │
   │  Tool Registry: tasks notes alarms calendar news github fs shell web │
   │                 memory                                               │
   └──────────────┬──────────────────────────────────┬────────────────────┘
        SQLite (WAL) + audit log             Memory Engine (same SQLite DB)
```

## 2. Activation

- **One mic owner.** A single `InputStream` fans audio out to both detectors, so they never fight over the device. This replaces the standalone stream in `jarvis.py`.
- **Double clap.** I'll port your adaptive-noise-floor RMS logic, including the retrigger arming and gap window. I'll also remove the run-once-per-process limit and the hardcoded welcome actions.
- **"FRIDAY wake up".** The default engine is Vosk with a grammar restricted to that phrase plus `[unk]`. It's offline, light enough to run 24x7, and needs no account. Porcupine with a custom keyword is the optional swap.
- **Fusion.** Either trigger alone, or both together, opens a session. A debounce prevents double-fires.
- **Waking is not authorization.** Anyone's voice, or a video playing on your speakers, can say the phrase. A wake only opens a listening window. It never grants privileges, and the confirmation gate carries all the weight.
- **Voice session.** After activation, VAD segments your speech. Local `faster-whisper` handles STT. TTS uses ElevenLabs, as in `jarvis.py`, with its WAV caching and a local SAPI fallback, and supports barge-in.

## 3. Brain and provider layer

- Internally everything uses one canonical message format, with `LLMProvider` as the interface.
- **`FridayProvider`** talks to your **local OmniRoute gateway** (`http://localhost:20128`): OpenAI-style `POST /v1/chat/completions`, `Authorization: Bearer <key>`, native `tool_calls` (confirmed by the probes in `probe_tests/`). The key lives in the OS keyring. Authentication sits behind a pluggable `AuthStrategy` and the wire format behind a codec (`openai` now; `messages` and `text` kept as fallbacks).
- **Model name.** The gateway only accepts names it knows (combos such as `auto/best-reasoning`, or `provider/model`). A bare `friday` is rejected, so either create a combo named `friday` in OmniRoute or point `model` at an existing one.
- **Thinking models.** Reasoning tokens count against `max_tokens` (the probe spent 195 of 202 thinking), so budgets are generous, a reply truncated to nothing is reported as truncated rather than as an error, and tool-call arguments that are not valid JSON are bounced back to the model instead of running with empty arguments.
- **Tool calling fallback.** If the endpoint ever rejects native tool-use, the provider switches to a strict JSON tool-call protocol. Calls are parsed, schema-validated and rejected if malformed.
- `python -m friday check-provider` live-tests the configured endpoint (plain reply and a tool call) without printing the key.
- The loop carries over the earlier fixes: it executes all tool calls in one response, trims history only on turn boundaries, uses typed errors, and retries with backoff. It also adds an iteration cap and a per-turn budget.

## 4. Memory and context window (built in)

Everything lives in the same local SQLite database as the audit log. No external service, no network.

### 4.1 Three layers

| Layer | What it holds | How it stays current |
|---|---|---|
| **Context window** | The live conversation (`Session.history`), kept under `max_history_tokens`. | Trimmed on whole-turn boundaries only, so a tool call is never separated from its result. |
| **Rolling summary** | One summary per session of everything that scrolled out of the window. | When turns are trimmed, they are folded into the summary (by the model if `use_model`, otherwise a compact digest of what you asked). Capped at `summary_max_chars`. |
| **Long-term memory** | Durable facts, preferences and episodes, with importance, pinning, usage counts and provenance. | Auto-extraction from your own messages, the `memory_remember` tool, and the CLI. Deduplicated on normalised text. |

A separate **turn log** keeps each exchange (your text and FRIDAY's final reply, never tool traffic) so the last few clean turns are restored into the session after a restart.

### 4.2 Every turn

1. **Recall.** The first user message of the turn is the query. Pinned memories come first, then the best matches ranked by relevance (FTS5 bm25, with a LIKE fallback), importance and recency. The rolling summary is included too.
2. **Inject.** Recalled items go into the turn's first user message inside `<recalled_data>` envelopes under `recall_max_chars`, for that model call only. They are never in the system prompt and never written back into the history.
3. **Commit.** After the turn: the exchange is logged; if the turn was clean (no untrusted content still in the window), durable facts are extracted from **your message only**.
4. **Overflow.** At the start of the next turn, anything trimmed from the window is summarised before it is gone.

### 4.3 Memory poisoning guard

Memory is persistent, so anything written into it can attack every future turn. Rules, all enforced in code:

- Auto-extraction reads only your own typed or spoken text, and only after a clean turn.
- `memory_remember` is a T1 side-effecting tool. On a tainted turn the policy engine forces your confirmation, and the saved memory is labelled `approved`. Otherwise it is labelled `assistant`; things you said directly are `user`.
- Secrets are refused (the same redactor that scrubs tool output checks every memory, summary and turn-log line).
- Recalled text is data, wrapped as `<recalled_data>` and labelled with its id, kind, date and provenance. It never taints a turn (otherwise every turn would be tainted); the guards above are what keep it clean.
- A turn that touched untrusted content contributes only your words to the summary and turn log, not FRIDAY's reply. It is not restored after a restart.
- `memory_forget` is T2: it always asks you first. Memory writes, forgets and summaries are audited.

### 4.4 One thread across channels

A single logical session is shared by desktop, voice and Telegram. Each message is tagged with its source channel.

### 4.5 Telegram

FRIDAY gets **its own new bot** (create it with BotFather) and polls the Bot API directly; its token goes in the OS keyring. Hermes stays independent and keeps its own bot, so there is no `getUpdates` conflict. FRIDAY accepts commands only from your Telegram user ID and sends confirmation cards with HMAC-signed buttons. Telegram arrives in tranche 5.

### 4.6 Ownership

FRIDAY's database is the only authority for memory. Tasks, notes and alarms stay local as structured data; the memory engine does not mirror them, and the model reads them through their own tools.

## 5. Tools

Every tool registers with a JSON schema, a risk tier and a taint policy:

| Tool group | Notes |
|---|---|
| Tasks, Notes | SQLite replaces JSON. **Decision:** the 24x7 daemon has concurrent writers, and WAL gives atomicity for free. Search and export still work, and `.md` export is kept. |
| Alarms, Reminders | Asyncio scheduler with a persistent store. Stores full datetimes, fires missed alarms after sleep or wake, and delivers via tray, voice and Telegram. |
| Calendar | Google OAuth, with a conflict check before create and real event durations. |
| News | RSS fetched through the web gateway. Summaries come from the quarantined summarizer (section 6). |
| GitHub | Read repos, PRs, issues and diffs. Draft reviews and comments. Posting needs confirmation. Token in the OS keyring. |
| Filesystem | Read, create and edit anywhere you own, within the policy below. |
| Shell, Code | Runs without `shell=True` where possible, with timeout, output cap and temp working directory. |
| Web | Fetcher that strips scripts, caps size, blocks private IP ranges (SSRF), and revalidates redirects. |
| Memory | `memory_search` (T0), `memory_remember` (T1), `memory_forget` (T2). **Built, tranche 1.** |

## 6. Security model

No prompt is a security boundary, so every rule below is enforced in code. Prompt text is only a hint.

**Risk tiers**

| Tier | Examples | Gate |
|---|---|---|
| T0 | Read tasks, notes, memory, local files outside the denylist | Auto |
| T1 | Add task or note, save a memory, create a new file in the workspace | Auto (confirmed if the turn is tainted) |
| T2 | Web fetch/scrape, edit existing files, GitHub comments, Telegram sends, shell reads, forget a memory | Confirm: click, typed, or voice yes with readback |
| T3 | Delete, overwrite, shell commands that change state, installs, settings, anything touching credentials | Confirm: click, typed or Telegram button, **or** voice with a random challenge phrase |

**Decision:** I recommend voice-only approval never covers T3 without the challenge phrase, because a spoofed or replayed "yes" is a real attack. You can loosen this.

**Defense layers**

1. **Trust separation.** Only your typed input, your voice in an active session, and your Telegram ID are trusted. Web pages, files, GitHub text, RSS and recalled memory are data wrapped in labeled envelopes. They are never placed in the system role.
2. **Taint tracking.** Once untrusted content enters a turn, every side-effecting tool in that turn is forced to confirm, whatever its tier.
3. **Quarantined summarizer.** Large untrusted blobs (pages, diffs, feeds) go through a tool-less model call first. The main agent only sees that summary, still marked tainted.
4. **Code-built confirmation cards.** The card shows the exact arguments, rendered by code, not by the model. Approvals are bound to a hash of those arguments, are single-use, and expire after about 60 seconds.
5. **Filesystem policy.** A denylist (SSH keys, browser profiles, `.env` files, credential stores) always requires T3. Deletes go to the recycle bin with an undo journal, never a hard delete.
6. **Secrets handling.** All secrets live in the OS keyring and never enter the model context. Tool output, memories, summaries and the turn log are redacted.
7. **Output safety.** The UI doesn't auto-load remote images or links from tainted text, which closes the markdown exfiltration trick.
8. **Containment.** There's an append-only, hash-chained audit log, rate limits and a hard loop cap. A kill switch (hotkey, UI button and Telegram command) halts the agent instantly.
9. **Memory poisoning guard.** See section 4.3.

This bounds the damage from an injection but cannot make one impossible. The confirmation gate is the last line, so I'd rather it be strict.

## 7. UI

- **HUD.** A frameless translucent orb that shows idle, listening, thinking, speaking and awaiting-confirmation.
- **Control box.** Text input, transcript, tool activity feed, and a confirmation dock showing pending action cards.
- **Status chips.** Mic, activation state, memory, Telegram link and model.
- **Panels.** Tasks, alarms, notes and memories (browse, pin, forget), plus settings and the kill switch.
- **Tray.** Keeps FRIDAY alive with the window closed.

## 8. Repo layout

```
friday-v2/
├── friday/
│   ├── core/        daemon, config, bus, db, audit, session, agent_loop, killswitch, schema
│   ├── security/    policy, tiers, taint, confirm_broker, card, fs_rules, net_guard, secrets, ratelimit
│   ├── brain/       provider (base + friday + codecs), json_protocol, context_builder, summarizer, persona
│   ├── memory/      store (SQLite + FTS5), engine (recall, summary, extraction, restore)
│   ├── tools/       registry, builtin, memory_tools   (tranche 2: tasks, notes, alarms, fs, shell, web)
│   ├── channels/    console                           (later: ui_ws, voice, telegram)
│   ├── sensors/     (tranche 3: audio_hub, clap, wakeword, vad, stt, tts)
│   ├── ui/          (tranche 4: main_window, hud, control_box, panels, tray)
│   └── launcher/    (tranche 6: supervisor, autostart)
├── tests/           stdlib unittest suite
├── docs/            ARCHITECTURE.md, DEPLOYMENT.md
└── LICENSE, NOTICE, CHANGELOG.md, SECURITY.md, CONTRIBUTING.md, pyproject.toml, config.example.toml
```

## 9. Delivery order

1. **Core, security skeleton and built-in memory.** Config, secrets, DB, bus, audit, policy engine, confirmation broker, provider interface, tool registry, agent loop, memory engine. Runs headless. **Done: released as 0.1.0.**
2. **Local tools.** Tasks, notes, alarms with the scheduler, filesystem, shell and web.
3. **Sensors and voice.** Audio hub, clap, wake phrase, STT and TTS.
4. **UI.**
5. **Integrations.** Calendar, News, GitHub and Telegram (direct Bot API).
6. **Packaging.** Launcher, autostart, watchdog and tests.

Dropping Hermes removed the old tranche 3, so everything after tranche 2 moved up by one. Telegram only needs a new bot token from BotFather; Hermes is left alone.

## Open inputs

Nothing blocking. For Telegram (tranche 5): create the new bot with BotFather and send me your numeric Telegram user ID when we get there (the token goes into the keyring, never into chat or config). Optional now: create a combo named `friday` in OmniRoute so `model = "friday"` works.
