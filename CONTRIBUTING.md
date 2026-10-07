# Contributing

FRIDAY is built in tranches (see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), section 9). Changes
should keep the tranche boundaries clean and never weaken the security model.

## Set up

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -e ".[secrets]"      # add ,voice to work on the voice stack (needs a microphone to try it live)
```

## Check your change

```
python -W error::ResourceWarning -m unittest discover -s tests -t .
ruff check .
```

The suite uses only the standard library and must pass on Python 3.10 to 3.13, on Windows and Linux.

## Rules

- **Security is enforced in code.** A new tool declares a JSON schema, a risk tier and its output trust
  (`TRUSTED`, `RECALLED` or `UNTRUSTED`). Anything that changes state is side-effecting. Anything that
  reads web pages, files or third-party text returns `UNTRUSTED` output.
- **Tools that touch paths act on `ctx.resolved_paths`**, the paths the policy engine resolved and
  classified, never on the raw argument. A tool that reads or fetches third-party text returns `UNTRUSTED`
  output, and one whose error messages can carry that text sets `errors_untrusted`. Set `summarize_over`
  when a tool needs more than the default raw-output threshold.
- **Anything a tool stores for later** (tasks, notes, reminders, anything the model can read back) records
  whether the turn was tainted, and returns tainted rows as `UNTRUSTED` data.
- **Voice code (`friday/sensors`, `friday/channels/voice.py`)** must stay testable without hardware: every device,
  engine and clock is injected, and tests use the fakes in `tests/voice_helpers.py`. Heavy libraries (`sounddevice`,
  `numpy`, `vosk`, `faster-whisper`) are optional extras, imported lazily, and the core must keep working without them.
  Never download a model from the running core (only `friday fetch-models` does), never put spoken text on a command
  line, never speak the T3 challenge phrase, never pass a readback through a summariser, and never let FRIDAY's own
  speech reach the recorder.
- **Never route around the confirmation broker**, the policy engine or the redactor, even in tests of
  other features.
- **Secrets never go in code, config, logs or test fixtures.** Use the keyring (`friday set-secret`).
- **Every behaviour change gets a test**, and every security-relevant change gets a test that tries to
  break it.
- **Database changes are new migrations** appended to `friday/core/db.py`. Never edit a shipped one.
- **New source files start with the licence header:**

  ```python
  # Copyright 2026 Alpha (code8286)
  # SPDX-License-Identifier: Apache-2.0
  ```

- A tool that must refuse something (a critical path, an unsafe URL) refuses in the policy engine, before an
  approval card exists, so the user is never asked to approve something that can't be done.
- Record user-visible changes under `[Unreleased]` in `CHANGELOG.md`.

## Licence

By contributing you agree that your contributions are licensed under the Apache License 2.0, as
described in section 5 of [`LICENSE`](LICENSE).
