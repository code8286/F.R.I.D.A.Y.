# Contributing

FRIDAY is built in tranches (see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), section 9). Changes
should keep the tranche boundaries clean and never weaken the security model.

## Set up

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -e ".[secrets]"
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

- Record user-visible changes under `[Unreleased]` in `CHANGELOG.md`.

## Licence

By contributing you agree that your contributions are licensed under the Apache License 2.0, as
described in section 5 of [`LICENSE`](LICENSE).
