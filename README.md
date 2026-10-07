# F.R.I.D.A.Y.

A standalone, always-on desktop assistant with full access to your machine and a security model built
in code, not in prompts.

**Version 0.3.0, tranches 1–3:** the headless core, security model, built-in memory, model provider, the
local tools (tasks, notes, alarms, files, shell, web) and, optionally, voice: a double clap or "FRIDAY wake up",
speech recognition on your machine and spoken replies. It runs in a terminal today. The desktop UI and Telegram
come in later tranches.

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.10–3.13](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue.svg)
![Dependencies: none](https://img.shields.io/badge/runtime%20deps-none-green.svg)

## Quick start

```
pip install ".[secrets]"               # from this folder; installs `friday` and `keyring`
friday run                             # offline echo provider, no API key needed
```

To use the real model through your local OmniRoute gateway:

```
friday set-secret friday_api_key       # stored in the OS keyring, never in config (needs `keyring`)
friday init                            # prints the config path; set [provider] kind = "friday"
friday check-provider                  # live test: plain reply + a native tool call
friday run
```

The full walkthrough, including configuration, upgrades and troubleshooting, is in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## What it does

| Area | What you get |
|---|---|
| **Core** | An asyncio daemon (`FridayCore`) with SQLite (WAL) storage and migrations, an event bus, a kill switch, and an agent loop with retries, budgets and history repair. |
| **Security** | Risk tiers T0 to T3, taint tracking with data envelopes, a policy engine, a confirmation broker (single-use approvals bound to exact arguments), filesystem and SSRF rules, keyring secrets with redaction, and a hash-chained audit log. |
| **Model** | `FridayProvider`, with an OpenAI-compatible codec verified against OmniRoute, pluggable auth, and a JSON tool-protocol fallback. An offline echo provider is included. |
| **Memory** | Long-term memories with full-text search, recalled each turn as data. Turns that leave the context window are folded into a rolling summary, facts are extracted from your own messages, and the session is restored after a restart. Memory is guarded against poisoning. |
| **Local tools** | Tasks, notes, reminders and alarms (persistent scheduler, missed alarms fire on restart), file tools with an undo journal and a trash folder, a shell tool, and a web fetcher pinned against SSRF. |
| **Voice** (optional, off by default) | One microphone owner, a double-clap detector, a "FRIDAY wake up" phrase (Vosk), voice activity detection, local speech-to-text (faster-whisper) and spoken replies (ElevenLabs, with a system-voice fallback). Half-duplex, with barge-in ("stop"), and spoken approvals that follow strict rules (below). |
| **Interfaces** | A console channel with approvals, a voice channel, and the `friday` CLI. |

| Group | Tools | Gate |
|---|---|---|
| Basics, memory | `get_time`, `list_tools`, `memory_search`, `memory_remember`, `memory_forget` | T0 to T2 |
| Tasks | `task_add`, `task_list`, `task_update`, `task_delete` | T1, delete T2 |
| Notes | `note_add`, `note_list`, `note_search`, `note_read`, `note_update`, `note_delete`, `note_export` | T1, delete and body replacement T2 |
| Reminders | `reminder_set`, `reminder_list`, `reminder_cancel`, `reminder_snooze` | T1 |
| Files | `fs_list`, `fs_read`, `fs_search` (T0) · `fs_write` (T1/T2) · `fs_edit` (T2) · `fs_move`, `fs_delete` (T3) · `fs_trash_list`, `fs_undo` | by path, see below |
| Shell | `shell_run` (one program, no shell) | T2 for version queries, T3 otherwise |
| Web | `web_fetch` (GET) | T2, every call |

**Files** are limited to your home folder and the FRIDAY workspace (`[security] fs_roots`); anything else, and
anything on the protected list (keys, browser profiles, `.env`, shell history, FRIDAY's own data and code), needs a
T3 approval even to read. Deletes go to FRIDAY's trash and can be undone with `fs_undo` for 30 days. File, web and
shell output is untrusted data: it taints the turn, so anything that changes something afterwards needs approval.

### CLI

| Command | Purpose |
|---|---|
| `friday run` | Start the core with the console channel (the default command). |
| `friday init` / `show-config` | Write the default config / print the effective one. |
| `friday set-secret NAME` / `delete-secret NAME` | Manage keyring secrets. |
| `friday check-provider` | Live-test the model endpoint without printing the key. |
| `friday verify-audit` | Verify the audit log hash chain. |
| `friday audio-devices` | List microphones and speakers. |
| `friday voice-check [--seconds N] [--say TEXT]` | Test the microphone, speech engines and models without opening a session. |
| `friday fetch-models [vosk\|whisper\|all] [--force]` | The one command that downloads the speech models (the running core never does). |
| `friday memory list\|search\|add\|forget\|pin\|unpin\|summary` | Inspect and edit memory offline. |
| `friday show tasks\|notes\|reminders\|trash` | Read-only views of your local data. |
| `friday --version` | Print the version. |

In the console, type a message to talk to FRIDAY. Answer approvals with `yes` / `no` (T2) or the
4-digit code (T3). Other commands: `/pending`, `/kill`, `/reset`, `/audit`, `/help`, `/exit`. With the
echo provider, `!tool get_time {}` triggers a tool call. Reminders appear in the console when they fire (and are spoken when voice is on).

### Voice

Voice is **off until you turn it on** (`[voice] enabled = true`), so nothing listens to the microphone by default.
Setup is in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), section 7. In short:

```
pip install ".[voice]"                 # sounddevice, numpy, vosk, faster-whisper
friday fetch-models all                # one-time model download (about 300 MB)
friday set-secret elevenlabs_api_key   # optional; without it FRIDAY uses the system voice
friday voice-check                     # then set [voice] enabled = true and run `friday run`
```

A double clap or "FRIDAY wake up" opens a **listening window**: FRIDAY says "Yes, Alpha?", then listens for about
20 seconds. Waking grants no authority. FRIDAY never listens while it is speaking, "stop" cuts it off, and a spoken
**yes** approves a T2 action only after FRIDAY has read the exact action back, in full, and only if the action is short
enough to hear in full. A T3 action needs the challenge phrase shown on screen, which is never spoken. Anything else is
approved on screen.

## How a tool call is protected

```
model asks for a tool
  → schema validation
  → policy engine: kill switch, rate limits, tier, path/URL rules, taint
  → confirm?  code-built card → approval bound to sha256(tool, exact args), single use, 60 s, per-tier channel rules
  → run with timeout → redact secrets → wrap untrusted output as data (taints the session) → audit log
```

Key decisions:

- **Taint outlives the turn.** It lasts while untrusted content is in the context window, so an
  injection can't wait for your next message.
- **Recalled memory is data but doesn't taint.** Instead, it is protected at write time:
  auto-extraction reads only your own messages after clean turns, and a memory write on a tainted turn
  needs your approval.
- **The voice T3 challenge phrase** is shown on screen and never spoken aloud.
- **The audit log is tamper-evident** (keyed with an HMAC key when a keyring is available), not
  tamper-proof.

See [`SECURITY.md`](SECURITY.md) for the threat model, known limits and a hardening checklist.

## Configuration at a glance

The config file is `config.toml` in `%APPDATA%\friday\` (Windows), `~/.local/share/friday/` (Linux) or
`~/Library/Application Support/friday/` (macOS). Every option is documented in
[`config.example.toml`](config.example.toml).

| Section | Notable keys |
|---|---|
| `[provider]` | `kind` (`echo`/`friday`), `base_url` (`http://localhost:20128`), `model` (`auto/best-reasoning`, or `friday` once that combo exists in OmniRoute), `codec` (`openai`) |
| `[memory]` | `enabled`, `use_model` (false = fully offline), `auto_extract`, `recall_k`, `restore_turns` |
| `[security]` | `confirm_ttl_s`, `fs_roots`, `allowed_telegram_ids`, `voice_t3_requires_challenge` |
| `[tools]` | switch groups on or off (`tasks`, `notes`, `reminders`, `fs`, `shell`, `web`), `trash_retention_days` |
| `[conversation]` | `user_name`, `timezone` |
| `[voice]` | `enabled` (false), `activation` (`either`/`both`/`clap`/`wake`), `wake_phrases`, `session_idle_s`, `tts_engine` (`elevenlabs`/`local`/`none`), `elevenlabs_voice_id`, `input_device`, `output_device` |

## Development

```
python -W error::ResourceWarning -m unittest discover -s tests -t .   # 446 tests, stdlib only (voice tests use fakes: no microphone needed)
ruff check .
```

CI runs the suite on Ubuntu and Windows with Python 3.10 to 3.13. Read
[`CONTRIBUTING.md`](CONTRIBUTING.md) before adding tools: every tool declares a schema, a risk tier and
its output trust.

## Project documents

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Full design and delivery order (tranches 1–6). |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Install, configure, verify, upgrade, roll back. |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in each release. |
| [`SECURITY.md`](SECURITY.md) | Security model, limits, how to report a vulnerability. |

## Roadmap

1. ~~Core, security and memory~~ (0.1.x)
2. ~~Local tools: tasks, notes, alarms with scheduler, filesystem, shell, web~~ (0.2.0)
3. ~~Sensors and voice: double clap, "FRIDAY wake up", STT, TTS~~ (0.3.0)
4. Desktop UI (PySide6): HUD, control box, approvals dock, tray
5. Integrations: Calendar, News, GitHub, Telegram (its own bot)
6. Packaging: launcher, autostart, watchdog

## Licence

Licensed under the [Apache License 2.0](LICENSE). Copyright 2026 Alpha (code8286). See [`NOTICE`](NOTICE).
