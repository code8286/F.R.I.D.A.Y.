# Deploying FRIDAY 0.3 (tranche 3)

Tranche 3 is the headless core, the local tools (tasks, notes, reminders, files, shell, web) and optional voice
(double clap, wake phrase, local speech recognition, spoken replies). It runs in a terminal with the console channel.
The desktop UI, Telegram, autostart and the supervisor come in later tranches (see `ARCHITECTURE.md`, section 9).

## 1. Requirements

- Python 3.10 or newer (3.11+ recommended), on Windows, Linux or macOS.
- The OmniRoute gateway running locally at `http://localhost:20128`, with an API key. Without it,
  FRIDAY still runs on the offline echo provider.
- No other runtime dependencies. The `keyring` extra is strongly recommended. Voice adds the optional `voice` extra (section 7).

## 2. Install

From the `friday-v2` folder:

```
python -m venv .venv
.venv\Scripts\activate              # Linux/macOS: source .venv/bin/activate
pip install ".[secrets]"            # installs the `friday` command and keyring
friday --version
```

Without pip you can also run it in place with `python -m friday ...` from the `friday-v2` folder. In
that case install the one optional package yourself: `python -m pip install keyring`. Storing the API
key (step 4) needs it.

## 3. Configure

```
friday init                         # writes the default config.toml and prints its path
```

| OS | Config and data directory |
|---|---|
| Windows | `%APPDATA%\friday\` |
| Linux | `~/.local/share/friday/` (or `$XDG_DATA_HOME/friday/`) |
| macOS | `~/Library/Application Support/friday/` |

Override it with `--config <file>`, `FRIDAY_CONFIG`, or `FRIDAY_DATA_DIR`. The directory holds
`config.toml`, `friday.db` (memory, tasks, notes, reminders, audit log, turn log), plus a `trash/` folder for deleted files and `ws_token`. Back it up, and never commit it.

The settings you are most likely to change are in `config.toml`. Everything else is documented in
`config.example.toml`.

```toml
[provider]
kind     = "friday"                  # "echo" = offline
base_url = "http://localhost:20128"
model    = "auto/best-reasoning"     # or "friday", once you create that combo in OmniRoute

[conversation]
user_name = "Alpha"
timezone  = "Asia/Kolkata"

[memory]
use_model = true                     # false = fully offline memory (pattern-based)
```

**Upgrading from 0.2.x:** nothing to migrate (no database change). Your `config.toml` keeps working; the new `[voice]` section is
off by default and appears in `config.example.toml`.

**Upgrading from 0.1.x:** the database migrates itself on first start (v3 adds the task, note, reminder and
undo tables). Your existing `config.toml` keeps working; add the `[tools]` section and `security.fs_roots`
only if you want to change the defaults. Take a copy of `friday.db` first, because an older build cannot
open the migrated file.

**Upgrading from an earlier build:** a leftover `[hermes]` section is ignored with a note, so you can
delete it. If your `[provider]` block still says `codec = "messages"` or `path = "/v1/chat"`, replace it
with the block from `config.example.toml`.

## 4. Store the API key

```
friday set-secret friday_api_key    # input is hidden; stored in the OS keyring
```

This needs the `keyring` package (`python -m pip install keyring`, or install with the `[secrets]`
extra as in step 2). On Windows it stores the key in Credential Manager. Without `keyring`,
`set-secret` stops with a message telling you what to install. Nothing is written to disk.

On a headless machine with no OS keyring you can instead set the environment variable
`FRIDAY_SECRET_FRIDAY_API_KEY` (PowerShell: `$env:FRIDAY_SECRET_FRIDAY_API_KEY = "..."`) before
`friday run`. FRIDAY only reads it. The variable lives in your shell session or profile, so prefer the
keyring wherever one exists.

## 5. Check the endpoint

```
friday check-provider
```

Expected output is a plain reply, a native tool call, and `OK`. Common results:

| Output | Meaning |
|---|---|
| `error: the `keyring` package is not installed ...` | `python -m pip install keyring`, then repeat step 4. |
| `ProviderAuthError: API key ... is not set` | Run step 4. |
| `authentication rejected (401)` | Wrong key. Run step 4 again. |
| `Unable to determine provider for model` | `model` is not known to OmniRoute. Use `auto/best-reasoning` or create the combo. |
| `cannot reach provider` | OmniRoute isn't running, or `base_url` is wrong. |

## 6. Local tools (tranche 2)

All tools are on by default. Each group has a switch, and the filesystem reach is set under `[security]`:

```toml
[security]
fs_roots = ["~"]                     # folders FRIDAY may read and write. Writes outside them need a T3 code.

[tools]
tasks = true
notes = true
reminders = true
fs = true
shell = true
web = true
trash_retention_days = 30
```

Defaults keep reads inside your user profile and ask before anything that changes state: a T2 `yes`
for ordinary writes, shell commands from the read-only allowlist and web fetches; a 4-digit T3 code for
other shell commands, writes outside `fs_roots`, scripts and startup locations. Deleting or moving a drive
root, your home folder or FRIDAY's own folders is refused outright. To narrow the reach, list specific
folders, for example `fs_roots = ["~/Documents", "~/Downloads"]`. To turn a group off, set it to `false`.

Things to know:

- **Undo.** Deleted files go to `<data dir>/trash` and are purged after `trash_retention_days`. `fs_undo`
  reverses the last change recorded in the journal. `friday show trash` lists what can be undone.
- **Reminders** fire only while the core is running. A reminder that came due while it was stopped fires
  at the next start, marked late. Check them with `friday show reminders`.
- **Offline views.** `friday show tasks|notes|reminders|trash` read the database directly and do not need
  the daemon or the model.
- **Web.** Only `http` and `https` to public addresses. Private, loopback and link-local targets are
  blocked, including when a name resolves to one. Every fetch asks first.

## 7. Voice (tranche 3, optional)

Voice is **off by default**: with `[voice] enabled = false` nothing opens the microphone. To turn it on:

```
pip install ".[voice]"              # sounddevice, numpy, vosk, faster-whisper (optional extras, imported lazily)
friday fetch-models all             # one-time download; the running core never downloads anything
friday audio-devices                # list microphones and speakers (indexes and names)
friday set-secret elevenlabs_api_key   # optional, for the ElevenLabs voice (stored in the OS keyring)
```

On Linux `sounddevice` needs PortAudio (`sudo apt install libportaudio2`); for the local fallback voice install
`espeak-ng`. Windows needs nothing extra (the fallback voice is built in); on macOS the fallback is `say`.

Then edit `config.toml`:

```toml
[voice]
enabled             = true
activation          = "either"       # "either" | "both" | "clap" | "wake"
elevenlabs_voice_id = "YOUR_VOICE_ID"
# input_device = "USB"               # an index or part of a name from `friday audio-devices`
```

Check it before you rely on it:

```
friday voice-check                  # packages, models, devices, key, then 8 s of live clap/level readings
friday voice-check --say "Testing one two three"     # also speaks through your configured voices
friday run
```

`fetch-models` prints the SHA-256 of the Vosk download. Copy it into `voice.vosk_model_sha256` to pin it, and later
runs (or a `--force` refresh) will refuse a different file. Models live in `<data dir>/models`.

How it behaves:

- A **double clap** and/or **"FRIDAY wake up"** (per `activation`) opens a listening window. FRIDAY says
  "Yes, Alpha?" and listens until `session_idle_s` (20 s) of quiet. Opening a window launches nothing and grants nothing.
- While FRIDAY speaks, the recorder is off (plus a short echo guard), so it never hears itself. Say **"stop"** or
  **"FRIDAY stop"** to cut it off.
- If speech cannot be recognised or spoken (missing library, model or key), FRIDAY still runs: the console shows a
  `voice:` note saying what is missing, and replies stay on screen. ElevenLabs falls back to the system voice.
- Spoken approvals: T2 needs FRIDAY's full readback followed by a short "yes" (an action too long to read out in full is
  approved on screen). T3 needs the challenge phrase **printed in the console**; it is never spoken. "No" always cancels.
- Reminders are spoken when they fire, even with no window open (`speak_reminders = false` turns that off).
- `tts_engine = "local"` keeps all speech on the machine; `"elevenlabs"` sends each spoken reply's text (secrets redacted)
  to ElevenLabs. Speech recognition is always local.

Troubleshooting:

| Symptom | Likely cause |
|---|---|
| `microphone unavailable: ...` repeating | Another app has the device, or it was unplugged; FRIDAY retries every few seconds. Set `input_device`. |
| Clap never triggers | Run `friday voice-check` and watch the levels; lower `clap_min_rms` or `clap_spike_ratio` a little. |
| Claps trigger on speech | Raise `clap_spike_ratio`. A clap must be short; sustained noise is ignored. |
| Wake phrase never fires | Vosk model missing (`friday fetch-models vosk`), or the wrong microphone. `activation = "clap"` works without it. |
| "speech recognition failed" | The Whisper model is missing or incomplete: `friday fetch-models whisper --force`. |
| FRIDAY answers itself | Use headphones, or raise `echo_guard_ms`; check that `output_device` is not a loopback. |
| `ElevenLabs refused the request (HTTP 401)` | Wrong or expired key, or the account is out of quota: `friday set-secret elevenlabs_api_key`. |

## 8. Run

```
friday run
```

| In the console | Does |
|---|---|
| any text | talk to FRIDAY |
| `yes` / `no` | answer a pending T2 approval |
| the 4-digit code | approve a pending T3 action |
| `/pending` | list pending approvals |
| `/kill`, `/reset` | engage and release the kill switch |
| `/audit` | verify the audit log |
| `/help`, `/exit` | help, quit |

With voice on, the console also shows what was heard (`[voice] heard: ...`) and prints any T3 challenge phrase for you to say.

## 9. Verify a deployment

```
python -W error::ResourceWarning -m unittest discover -s tests -t .   # from the source folder
friday verify-audit
friday memory list
friday show tasks
friday voice-check                  # if you use voice
```

## 10. Upgrade and roll back

- **Upgrade:** `pip install --upgrade .` from the new source, then run `friday verify-audit` and
  `friday check-provider`. Database migrations run automatically and only move forward.
- **Roll back:** reinstall the previous version. If the database was already migrated to a newer
  schema, the older build refuses to open it ("database schema vN is newer than this build"). In that case, restore
  your backup of `friday.db` taken before the upgrade.
- **Reset memory only:** `friday memory forget <id>` per item. Deleting `friday.db` also deletes the
  audit log.

## Not yet available

There is no autostart or background service yet (tranche 6), no desktop UI (tranche 4) and no Telegram (tranche 5;
FRIDAY will use its own new bot token). Reminders and the
scheduler run only while `friday run` is open.
