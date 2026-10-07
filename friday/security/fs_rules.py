# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Filesystem policy (Architecture §6.5).

* Paths are fully resolved (``~``, ``..``, symlinks) BEFORE any decision, so traversal and symlink
  tricks cannot dodge the rules.
* A denylist (SSH keys, browser profiles, ``.env`` files, credential stores, FRIDAY's own database /
  token / config) always requires T3, even for reads.
* Writes under OS system roots are T3.
* `roots` (``[security] fs_roots``, plus the workspace) bound where file tools may go without a T3 approval; a path
  outside every root is T3 for any operation, reads included. ``roots=None`` means unrestricted (used by unit tests).
* Deletes never hard-delete: `friday.tools.fs_tools` moves to FRIDAY's trash and records an undo journal entry.
* Deleting or moving a drive root, the home folder, FRIDAY's own folders or any folder that contains one of them is
  refused outright (``ValueError`` -> the policy engine DENIES).

NOTE (TOCTOU): the decision is made on the resolved path; tools must operate on
`PathVerdict.resolved`, not on the raw argument the model supplied.
"""

from __future__ import annotations

import fnmatch
import os
import sys
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
    "*.ppk", "*.jks", "*.keystore", "*.ovpn", ".terraform.d", "credentials.toml", ".cargo-credentials*",
    # shell / REPL histories hold typed secrets
    ".bash_history", ".zsh_history", ".python_history", ".psql_history", ".mysql_history", ".node_repl_history",
    "consolehost_history.txt",
]

# Files that run by themselves later (shell start-up, interpreter hooks). Writing or editing one is T3, like a script.
PERSISTENCE_NAMES = [
    ".bashrc", ".bash_profile", ".bash_login", ".bash_logout", ".profile", ".zshrc", ".zshenv", ".zprofile", ".zlogin",
    ".gitconfig", ".gitattributes", "profile.ps1", "microsoft.powershell_profile.ps1", "microsoft.vscode_profile.ps1",
    "sitecustomize.py", "usercustomize.py", "*.pth", "autoexec.bat", ".xinitrc", ".xprofile", ".envrc",
]

RISKY_SUFFIXES = {
    ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".wsf", ".lnk", ".exe", ".dll", ".msi", ".scr", ".com", ".reg",
    ".sh", ".bash", ".zsh", ".desktop", ".command", ".jar", ".hta", ".cpl", ".appimage", ".service", ".plist",
}

# Matched as substrings of the casefolded posix-style full path.
PATH_SUBSTRINGS = [
    "/google/chrome/user data", "/microsoft/edge/user data", "/bravesoftware/", "/mozilla/firefox/profiles",
    "/.config/google-chrome", "/.config/chromium", "/application support/google/chrome",
    "/microsoft/credentials", "/microsoft/protect", "/microsoft/vault", "/windows/system32/config",
    "/etc/shadow", "/etc/sudoers", "/.config/gcloud", "/.docker/config.json", "/.config/gh/hosts.yml",
    "/.local/share/keyrings", "/library/keychains",
    # persistence locations: anything written here runs later without you
    "/start menu/programs/startup", "/.config/autostart", "/library/launchagents", "/library/launchdaemons",
    "/etc/cron", "/var/spool/cron", "/.config/systemd/user", "/.git/hooks/", "/.git/config", "/.vscode/tasks.json",
    # more browser, chat-app and tool credential stores
    "/opera software/", "/vivaldi/user data", "/.config/microsoft-edge", "/.config/vivaldi", "/.config/opera",
    "/application support/firefox", "/library/safari", "/library/cookies", "/discord/local storage", "/slack/local storage",
    "/telegram desktop/tdata", "/.config/rclone", "/.config/filezilla", "/.local/share/signal",
]

SYSTEM_ROOTS = [
    "/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc", "/lib", "/lib64", "/dev",
    "c:/windows", "c:/program files", "c:/program files (x86)", "c:/programdata",
]


_WIN_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def unsafe_path_reason(raw: str, windows: bool | None = None) -> str | None:
    """Reject path spellings that make the OS do something before any decision is made (UNC/SMB connections leak
    credentials, device names block, alternate data streams hide data). Pure string checks; never touches the disk."""
    win = sys.platform.startswith("win") if windows is None else windows
    flat = raw.replace("/", "\\") if win else raw
    if raw.startswith("\\\\") or (win and flat.startswith("\\\\")):
        return "network (UNC) and device paths are not allowed"
    if not win:
        return None
    rest = flat[2:] if len(flat) >= 2 and flat[1] == ":" and flat[0].isalpha() else flat
    if ":" in rest:
        return "alternate data streams (':' in a name) are not allowed"
    for part in rest.split("\\"):
        if part in ("", ".", ".."):
            continue
        if part.endswith((".", " ")):
            return "names ending in a dot or space are not allowed on Windows"
        if part.split(".")[0].strip().casefold() in _WIN_RESERVED:
            return "reserved device names are not allowed"
    return None


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
        roots: Iterable[Path | str] | None = None,
    ):
        self.workspace = self._real(workspace)
        self.roots: list[Path] | None = None
        if roots is not None:
            self.roots = [self.workspace, *(self._real(r) for r in roots)]
        self.protected_roots = [self._real(p) for p in protected_roots]
        self.extra_patterns = [_fold(p) for p in extra_patterns]

    # ---- path handling ----
    @staticmethod
    def _real(p: str | os.PathLike[str]) -> Path:
        return Path(os.path.realpath(os.path.expanduser(os.fspath(p))))

    def resolve(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
            raise ValueError("invalid path")
        bad = unsafe_path_reason(raw.strip())
        if bad:
            raise ValueError(bad)
        p = Path(os.path.expanduser(raw))
        if not p.is_absolute():
            p = self.workspace / p
        return Path(os.path.realpath(p))

    def _within(self, child: Path, parent: Path) -> bool:
        try:
            # casefold on every platform: macOS volumes and Windows are case-insensitive, and being stricter on Linux is harmless
            child_s, parent_s = os.path.normcase(str(child)).casefold(), os.path.normcase(str(parent)).casefold()
            return os.path.commonpath([child_s, parent_s]) == parent_s
        except ValueError:  # different drives
            return False

    def in_workspace(self, p: Path) -> bool:
        return self._within(p, self.workspace)

    def in_roots(self, p: Path) -> bool:
        return self.roots is None or any(self._within(p, r) for r in self.roots)

    def is_critical(self, p: Path) -> bool:
        """A path that must never be deleted or moved: a drive root, or anything containing home / FRIDAY's folders / a root."""
        if p.parent == p:
            return True
        keep = [self._real(Path.home()), self.workspace, *self.protected_roots, *(self.roots or [])]
        return any(self._within(k, p) for k in keep) or _fold(p.as_posix()) in SYSTEM_ROOTS

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

        if op in ("delete", "move", "overwrite") and self.is_critical(p):
            raise ValueError("refusing to delete or move a drive root, the home folder or a FRIDAY folder")

        denied = self.denied_reason(p)
        if denied:
            return PathVerdict(p, RiskTier.T3, (f"touches protected path: {denied}",), True)

        if not self.in_roots(p):
            return PathVerdict(p, RiskTier.T3, ("outside the folders FRIDAY is set up to use",), False)

        if op in READ_OPS:
            return PathVerdict(p, RiskTier.T0, (), False)

        if self._is_system(p):
            return PathVerdict(p, RiskTier.T3, ("writes under an OS system location",), False)

        name = p.name.casefold()
        if p.suffix.casefold() in RISKY_SUFFIXES or any(fnmatch.fnmatchcase(name, pat) for pat in PERSISTENCE_NAMES):
            return PathVerdict(p, RiskTier.T3, ("creates or changes an executable, script or start-up file",), False)

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
