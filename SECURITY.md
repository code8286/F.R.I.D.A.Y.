# Security

FRIDAY has full access to the machine it runs on, so its security model is part of the product, not an
add-on. This page summarises that model and its known limits. The full design is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), section 6.

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x (tranches 1–3) | Yes |
| 0.2.x | Upgrade to 0.3 if you use voice; otherwise supported |
| 0.1.x | Upgrade: it lacks the security review fixes for the tools |

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately to the maintainer
(GitHub: `code8286`) with steps to reproduce, the version (`friday --version`), and your OS and Python
version. You should get a reply within 7 days. Never include real API keys or tokens in a report.

## Model

- **No prompt is a security boundary.** Every rule below is enforced in code. The persona text is a hint
  to the model and nothing more.
- **Trusted input** is only your typed input (console, and the desktop UI over its local token-protected
  socket in a later tranche), your voice inside a voice session you opened, and your allow-listed Telegram
  user ID. Everything else is data.
- **Risk tiers and gates.** T0 runs automatically. T1 runs automatically unless the turn is tainted. T2
  and T3 always need your approval. Destructive actions, web fetches and web commands are T2 or T3.
- **Taint.** Output from web pages, files and other untrusted tools is wrapped in an
  `<untrusted_data>` envelope and taints the session while it is in the context window. While tainted,
  every side-effecting tool needs your approval, whatever its tier.
- **Approvals** are bound to a hash of the exact tool and arguments, are single use and expire after
  60 seconds. Cards are rendered by code from sanitised arguments, never by the model. Any channel can
  deny. T3 needs a typed 4-digit code, a signed Telegram button, or (by voice) a challenge phrase that is
  shown on screen and never spoken.
- **Memory poisoning guard.** Memory is written only from your own messages, or through
  `memory_remember`, which needs your approval on a tainted turn. Secrets are refused. Recalled memory
  is enveloped as data and never placed in the system prompt.
- **Secrets** live in the OS keyring (Windows Credential Manager, macOS Keychain, Secret Service) and
  never enter the model context or the config file. Known secrets are redacted from tool output, logs,
  memory and the audit trail.
- **Containment.** Rate limits, iteration, tool-call and wall-clock caps per turn, a kill switch that
  cancels running work and pending approvals, and an append-only, hash-chained audit log (keyed with an
  HMAC key from the keyring when one is available). Check it with `friday verify-audit`.
- **Filesystem rules.** Paths are resolved (`~`, `..`, symlinks) before any decision and tools act only on the
  resolved path. A denylist (SSH keys, browser profiles, credential stores, `.env` files, shell history, FRIDAY's own
  data and code) always needs T3, and so does anything outside `fs_roots` (default: your home folder) even to read.
  Creating or changing scripts, executables and start-up files is T3. Drive roots, your home folder and FRIDAY's
  folders cannot be deleted or moved at all. Deletes go to a trash folder, and edits, overwrites and moves are
  journalled so `fs_undo` can reverse them (an undo refuses if the file changed afterwards).
- **Network rules.** `web_fetch` always needs approval. The policy engine checks the URL without any DNS lookup,
  and the fetch then resolves the host, requires every address to be public (including addresses that hide an IPv4
  address), connects to that exact IP, re-validates every redirect, and refuses compressed bodies.
- **Shell rules.** No shell is involved: the model gives a program and an argument list. Every call needs approval
  (T2 for a short read-only list, T3 otherwise). The child gets an environment without `FRIDAY_*` variables or
  anything that looks like a key, token, password or URL with credentials, and its output is untrusted data.
- **Voice rules.** Voice is off by default and only your own session counts as trusted input. These are enforced in code:
  waking (a clap or the phrase) opens a listening window and grants nothing; the recorder is off while FRIDAY speaks and for
  a short guard afterwards, so FRIDAY never hears itself and a "yes" inside a spoken reply can never become an approval;
  only an approval raised by a turn that arrived **by voice** can be answered by voice (a request from a typed, scheduled
  or other turn is never read out and never answerable by voice, even with a window open); a T2 "yes" counts only after the
  readback (built by code from the exact arguments, spoken word for word, never summarised) has played to the end
  uninterrupted, only if it is a short clean "yes" with no refusal word, and only if speech began after the readback
  ended; an action that cannot be read out in full (more than four arguments, long values, nested options) can only be
  approved on screen; T3 needs the random challenge phrase, shown on screen and never spoken; any "no", "cancel" or
  "stop" denies; the kill switch stops speech, closes the window and drops queued turns. Spoken text is redacted before it
  reaches a text-to-speech provider, and audio is never stored or logged. Speech recognition runs on your machine.
- **Voice supply chain.** The running core never downloads anything. `friday fetch-models` is the only download: https
  only, a size cap, an overall time limit, no redirect to plain http, an optional SHA-256 pin (the hash is always printed),
  a hardened unzip (no absolute paths, `..`, symlinks or oversized archives) into a temp folder moved into place only on
  success. Models load with network access off.
- **Stored data from tainted turns.** Tasks, notes and reminders written while untrusted content was in the turn are
  flagged and come back as untrusted data.

## Known limits

- These defences limit what a prompt injection can do; they cannot make one impossible. The
  confirmation gate is the last line of defence, so read approval cards before you approve them.
- The audit log is tamper-evident, not tamper-proof. Without a keyring it is plain hash-chained, so
  someone with write access to the database could rewrite it consistently.
- An approval is only as trustworthy as the channel that delivers it. The UI and voice layers (later
  tranches) must authenticate their own input.
- The model endpoint is configured as plain HTTP to `localhost`. Point `base_url` at a remote host only
  over HTTPS.
- Windows-specific protections (owner-only file permissions via `icacls`, Credential Manager) are
  implemented but have not yet been verified on Windows. The CI workflow runs the suite there.
- Approving a shell command approves everything that program does. Read the card; `["python", "-c", ...]` can do
  anything you can. Programs a command starts in the background are not stopped when it exits normally.
- Worker threads can't be cancelled: if a timeout or the kill switch fires during a large file copy or a web read,
  the operation may finish in the background even though the model was told it failed. Web reads are bounded by a
  deadline.
- File writes keep permissions but not Windows ACLs, extended attributes or hard links.
- The home folder is readable without approval by default (`fs_roots = ["~"]`, minus the protected list). Narrow it
  in `config.toml` if you prefer.
- Windows-specific protections (UNC and device-path refusal, `taskkill` for process trees, owner-only permissions via
  `icacls`) are implemented and unit-tested only by their logic on Linux; the CI workflow runs the suite on Windows.

- **Voice cannot tell who is speaking.** There is no speaker recognition. Anyone near the microphone, or any audio
  played near it, can open a window and talk to FRIDAY. They still cannot approve anything above T1 without the
  readback "yes" (T2) or the on-screen challenge phrase (T3), but a T2 action raised by their voice command can be approved by
  them saying "yes" in the right moment. Keep voice off in shared spaces, or keep `activation = "clap"`, or approve on screen.
  "Voice" is trusted input only inside the window you opened.
- **ElevenLabs sees what FRIDAY says.** With `tts_engine = "elevenlabs"` the text of each spoken reply is sent to
  ElevenLabs (secrets are redacted first). Use `tts_engine = "local"` to keep it on the machine. Only fixed short phrases
  (the greeting) are cached on disk; replies are never cached.
- **The microphone paths are untested on real hardware in the cloud CI.** Run `friday voice-check` after installing, and
  report anything odd. Windows speech paths (System.Speech via PowerShell) have the same caveat as other Windows code.
- Whisper can mis-hear. A mis-heard command is still a command inside your window, and the approval rules above apply to
  anything that changes state.

## Hardening checklist for a deployment

1. Install the keyring extra (`pip install "friday-assistant[secrets]"`, or `pip install keyring` when
   running from source). Without it the API key can only come from an environment variable, and the
   audit log is not keyed.
2. Store the key with `friday set-secret friday_api_key`. Never put it in `config.toml` or a script.
3. Review `[security] fs_roots` and set it to the folders you actually want FRIDAY to reach.
4. Keep `allowed_telegram_ids` limited to your own numeric ID once Telegram lands.
5. Leave `voice_t3_requires_challenge = true` and `voice_t2_requires_readback = true`.
6. Voice is off by default. Turn it on only where you are comfortable with a microphone being open (a double clap or the wake phrase starts a window; nothing is recorded or transcribed before that). Pin the Vosk model hash (`voice.vosk_model_sha256`) after the first `friday fetch-models`.
7. Store the ElevenLabs key with `friday set-secret elevenlabs_api_key`, never in config.
8. Run `friday verify-audit` after updates, and whenever something looks off.
