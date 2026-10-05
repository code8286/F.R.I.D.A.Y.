# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Filesystem policy (Architecture §6.5).

* Paths are fully resolved (``~``, ``..``, symlinks) BEFORE any decision, so traversal and symlink
  tricks cannot dodge the rules.
* A denylist (SSH keys, browser profiles, ``.env`` files, credential stores, FRIDAY's own database /
  token / config) always requires T3, even for reads.
* Writes under OS system roots are T3.
* Deletes never hard-delete: tools must use `friday.tools.fs` recycle-bin + undo journal (tranche 2).

NOTE (TOCTOU): the decision is made on the resolved path; tools must operate on
`PathVerdict.resolved`, not on the raw argument the model supplied.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .tiers import RiskTier

READ_OPS = {"read", "list"}
WRITE_OPS = {"create", "edit", "delete", "move", "overwrite"}

# Matched against each individual path component (case-insensitive).
PART_PATTERNS = [
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12",
    "*.kdbx", "id_rsa*", "id_ed25519*", "id_ecdsa*", "id_dsa*", ".netrc", "_netrc", ".npmrc", ".pypirc",
    ".git-credentials", ".pgpass", "credentials.json", "token.json", "client_secret*.json",
    "login data", "cookies.sqlite", "key4.db", "logins.json", "keychains", "keyrings",
    ".mozilla", "ntuser.dat", "secrets.json", ".vault-token",
]

# Matched as substrings of the casefolded posix-style full path.
PATH_SUBSTRINGS = [
    "/google/chrome/user data", "/microsoft/edge/user data", "/bravesoftware/", "/mozilla/firefox/profiles",
    "/.config/google-chrome", "/.config/chromium", "/application support/google/chrome",
    "/microsoft/credentials", "/microsoft/protect", "/microsoft/vault", "/windows/system32/config",
    "/etc/shadow", "/etc/sudoers", "/.config/gcloud", "/.docker/config.json", "/.config/gh/hosts.yml",
    "/.local/share/keyrings", "/library/keychains",
]

SYSTEM_ROOTS = [
    "/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc", "/lib", "/lib64", "/dev",
    "c:/windows", "c:/program files", "c:/program files (x86)", "c:/programdata",
]


def _fold(p: str) -> str:
    return p.replace("\\", "/").casefold()


@dataclass(frozen=True)
class PathVerdict:
    resolved: Path
    tier: RiskTier
    reasons: tuple[str, ...]
    denied_by_list: bool = False


class FsRules:
    def __init__(
        self,
        workspace: Path,
        protected_roots: Iterable[Path] = (),
        extra_patterns: Iterable[str] = (),
    ):
        self.workspace = self._real(workspace)
        self.protected_roots = [self._real(p) for p in protected_roots]
        self.extra_patterns = [_fold(p) for p in extra_patterns]

    # ---- path handling ----
    @staticmethod
    def _real(p: str | os.PathLike[str]) -> Path:
        return Path(os.path.realpath(os.path.expanduser(os.fspath(p))))

    def resolve(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
            raise ValueError("invalid path")
        p = Path(os.path.expanduser(raw))
        if not p.is_absolute():
            p = self.workspace / p
        return Path(os.path.realpath(p))

    def _within(self, child: Path, parent: Path) -> bool:
        try:
            child_s, parent_s = os.path.normcase(str(child)), os.path.normcase(str(parent))
            return os.path.commonpath([child_s, parent_s]) == parent_s
        except ValueError:  # different drives
            return False

    def in_workspace(self, p: Path) -> bool:
        return self._within(p, self.workspace)

    # ---- denylist ----
    def denied_reason(self, p: Path) -> str | None:
        for root in self.protected_roots:
            if self._within(p, root) and not self.in_workspace(p):
                return "inside FRIDAY's own protected data"
        posix = _fold(p.as_posix())
        for part in (x.casefold() for x in p.parts):
            for pat in PART_PATTERNS:
                if fnmatch.fnmatchcase(part, pat):
                    return f"matches protected name {pat!r}"
        for sub in PATH_SUBSTRINGS:
            if sub in posix + "/":
                return f"inside protected location {sub.strip('/')!r}"
        for pat in self.extra_patterns:
            if fnmatch.fnmatchcase(posix, pat):
                return f"matches user denylist {pat!r}"
        return None

    def _is_system(self, p: Path) -> bool:
        posix = _fold(p.as_posix())
        return any(posix == r or posix.startswith(r + "/") for r in SYSTEM_ROOTS) and not self.in_workspace(p)

    # ---- classification ----
    def classify(self, raw: str, op: str) -> PathVerdict:
        if op not in READ_OPS | WRITE_OPS:
            raise ValueError(f"unknown filesystem op {op!r}")
        p = self.resolve(raw)

        denied = self.denied_reason(p)
        if denied:
            return PathVerdict(p, RiskTier.T3, (f"touches protected path: {denied}",), True)

        if op in READ_OPS:
            return PathVerdict(p, RiskTier.T0, (), False)

        if self._is_system(p):
            return PathVerdict(p, RiskTier.T3, ("writes under an OS system location",), False)

        exists = p.exists()
        if op in ("delete", "move", "overwrite"):
            return PathVerdict(p, RiskTier.T3, (f"{op} changes or removes existing data",), False)
        if op == "edit":
            if exists:
                return PathVerdict(p, RiskTier.T2, ("edits an existing file",), False)
            op = "create"
        # create
        if exists:
            return PathVerdict(p, RiskTier.T3, ("would overwrite an existing file",), False)
        if self.in_workspace(p):
            return PathVerdict(p, RiskTier.T1, ("creates a new file in the workspace",), False)
        return PathVerdict(p, RiskTier.T2, ("creates a file outside the workspace",), False)
