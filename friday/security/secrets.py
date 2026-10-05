# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Secrets handling: OS keyring storage, redaction, and user-only token files.

Secrets never enter the model context. Everything that leaves a tool, an error message, the audit log
or a confirmation card passes through `Redactor`. Known secret values are redacted exactly; common
token shapes are redacted by pattern as a second net.
"""

from __future__ import annotations

import os
import re
import secrets as _secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol

from ..core.errors import SecretStoreUnavailable

REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{16,}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b"),  # Telegram bot token
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b(\s*[:=]\s*)(['\"]?)[^\s'\",;]{6,}\3"),
]


class Redactor:
    def __init__(self, min_len: int = 6):
        self._values: set[str] = set()
        self._min_len = min_len

    def add(self, secret: str | None) -> None:
        if secret and len(secret) >= self._min_len:
            self._values.add(secret)

    def text(self, s: str) -> str:
        for value in sorted(self._values, key=len, reverse=True):
            if value in s:
                s = s.replace(value, REDACTED)
        for pat in _PATTERNS:
            if pat.groups >= 3:
                s = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", s)
            else:
                s = pat.sub(REDACTED, s)
        return s

    def obj(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.obj(k) if isinstance(k, str) else k: self.obj(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.obj(v) for v in value]
        return value

    __call__ = obj


class SecretBackend(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class KeyringBackend:
    SERVICE = "friday"

    def __init__(self) -> None:
        import keyring  # optional dependency

        self._kr = keyring

    def get(self, name: str) -> str | None:
        return self._kr.get_password(self.SERVICE, name)

    def set(self, name: str, value: str) -> None:
        try:
            self._kr.set_password(self.SERVICE, name, value)
        except Exception as exc:  # keyring.errors.KeyringError, NoKeyringError, backend-specific
            raise SecretStoreUnavailable(
                f"the OS keyring refused to store {name!r} ({type(exc).__name__}). "
                "On a headless machine, set FRIDAY_SECRET_" + name.upper() + " in the environment instead."
            ) from exc

    def delete(self, name: str) -> None:
        try:
            self._kr.delete_password(self.SERVICE, name)
        except Exception:
            pass  # deleting a secret that does not exist is not an error


def no_keyring_message(name: str = "friday_api_key") -> str:
    return (
        "the `keyring` package is not installed, so FRIDAY has nowhere safe to store secrets.\n"
        f"  Fix:  {sys.executable} -m pip install keyring\n"
        f"        then run again:  {sys.executable} -m friday set-secret {name}\n"
        f"  Or, for this session only, set the environment variable FRIDAY_SECRET_{name.upper()}."
    )


class EnvBackend:
    """Read-only fallback: FRIDAY_SECRET_<NAME> environment variables (NAME upper-cased)."""

    def get(self, name: str) -> str | None:
        return os.environ.get("FRIDAY_SECRET_" + name.upper())

    def set(self, name: str, value: str) -> None:
        raise SecretStoreUnavailable(no_keyring_message(name))

    def delete(self, name: str) -> None:
        raise SecretStoreUnavailable(no_keyring_message(name))


class MemoryBackend:
    def __init__(self, initial: dict[str, str] | None = None):
        self._d = dict(initial or {})

    def get(self, name: str) -> str | None:
        return self._d.get(name)

    def set(self, name: str, value: str) -> None:
        self._d[name] = value

    def delete(self, name: str) -> None:
        self._d.pop(name, None)


class SecretStore:
    def __init__(self, backend: SecretBackend | None = None, redactor: Redactor | None = None):
        if backend is None:
            try:
                backend = KeyringBackend()
            except ImportError:
                backend = EnvBackend()
        self.backend = backend
        self.redactor = redactor or Redactor()

    def get(self, name: str) -> str | None:
        try:
            value = self.backend.get(name)
        except Exception:
            value = None
        if value is None and not isinstance(self.backend, EnvBackend):
            value = EnvBackend().get(name)  # env var as a last-resort fallback
        self.redactor.add(value)
        return value

    def require(self, name: str) -> str:
        value = self.get(name)
        if not value:
            raise KeyError(f"secret {name!r} is not set (python -m friday set-secret {name})")
        return value

    def set(self, name: str, value: str) -> None:
        self.backend.set(name, value)
        self.redactor.add(value)

    def delete(self, name: str) -> None:
        self.backend.delete(name)

    def audit_hmac_key(self, create: bool = True) -> bytes | None:
        """Per-install key for the keyed audit chain. None when no persistent backend can hold it
        (the log is then plain hash-chained, which still detects edits but not a full rewrite)."""
        try:
            existing = self.get("audit_hmac_key")
            if existing:
                return bytes.fromhex(existing)
        except ValueError:
            return None
        if not create:
            return None
        key = _secrets.token_bytes(32)
        try:
            self.set("audit_hmac_key", key.hex())
        except Exception:
            return None
        return key


# --------------------------------------------------------------------------- user-only files
def restrict_to_user(path: Path) -> None:
    if sys.platform.startswith("win"):
        user = os.environ.get("USERNAME")
        if user:
            try:
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
                    check=False, capture_output=True, timeout=10,
                )
            except (OSError, subprocess.SubprocessError):
                pass
    else:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def ensure_token_file(path: Path) -> str:
    """Return the WebSocket auth token, creating it (0600 / owner-only ACL) on first use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    token = _secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token)
    restrict_to_user(path)
    return token
