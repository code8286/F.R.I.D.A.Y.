# Deploying FRIDAY 0.1 (tranche 1)

Tranche 1 is the headless core. It runs in a terminal with the console channel. The desktop UI, voice,
Telegram, autostart and the supervisor come in later tranches (see `ARCHITECTURE.md`, section 9).

## 1. Requirements

- Python 3.10 or newer (3.11+ recommended), on Windows, Linux or macOS.
- The OmniRoute gateway running locally at `http://localhost:20128`, with an API key. Without it,
  FRIDAY still runs on the offline echo provider.
- No other runtime dependencies. The `keyring` extra is strongly recommended.

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
`config.toml`, `friday.db` (memory, audit log, turn log) and `ws_token`. Back it up, and never commit it.

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

## 6. Run

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

## 7. Verify a deployment

```
python -W error::ResourceWarning -m unittest discover -s tests -t .   # from the source folder
friday verify-audit
friday memory list
```

## 8. Upgrade and roll back

- **Upgrade:** `pip install --upgrade .` from the new source, then run `friday verify-audit` and
  `friday check-provider`. Database migrations run automatically and only move forward.
- **Roll back:** reinstall the previous version. If the database was already migrated to a newer
  schema, the older build refuses to open it ("database schema vN is newer than this build"). In that case, restore
  your backup of `friday.db` taken before the upgrade.
- **Reset memory only:** `friday memory forget <id>` per item. Deleting `friday.db` also deletes the
  audit log.

## Not in tranche 1

There is no autostart or background service yet (tranche 6), no desktop UI (tranche 4), no voice
(tranche 3) and no Telegram (tranche 5; FRIDAY will use its own new bot token). The only built-in
tools are `get_time`, `list_tools` and the memory tools. Local tools arrive in tranche 2.
