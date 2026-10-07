# FRIDAY v2 — Tranche 2 build log

**Status (2026-10-06, released as 0.2.0):** Tranche 2 (local tools) is built, reviewed, documented and delivered to `Projects/F.R.I.D.A.Y/friday-v2/` on Alpha's machine. 288 tests (stdlib only) pass on Python 3.10 (device, also under `-W error::ResourceWarning`), 3.11, 3.12 and 3.13; ruff is clean. `friday --version` reports 0.2.0.

**Scope decided with Alpha:** the full tranche (tasks, notes, reminders with a persistent scheduler, filesystem, shell, web), all behind the existing tiers, taint and confirmation gates. Filesystem reach: the whole user profile (`security.fs_roots = ["~"]`); writes keep their tiers and writes outside the roots are T3.

## Also shipped in this stretch

- **0.1.1:** `set-secret` / `delete-secret` no longer dump a traceback when `keyring` is missing. Typed `SecretStoreUnavailable`, an actionable message (exact `pip install keyring` for the running interpreter, env-var alternative), docs updated. The key is never written to disk as a fallback.
- **Provider verified live:** `friday check-provider` against OmniRoute (`auto/best-reasoning`, codec `openai`, bearer auth) returned a plain reply and a native tool call, so the open item from tranche 1 is closed.

## Delivered

- **Personal data** (`friday/personal/`): `TaskStore`, `NoteStore`, `ReminderStore`, `parse_when`, `next_occurrence`, and an asyncio `Scheduler` (persistent, thread-safe `poke`, missed reminders fire at start and are flagged late, repeats none/hourly/daily/weekdays/weekly). A firing reminder is published on the bus as `reminder.due`, shown by the console and written to the audit log. It never reaches the model. DB migration v3: `tasks`, `notes`, `reminders`, `fs_journal`.
- **Tools:** `task_add/list/update/delete`; `note_add/list/search/read/update/delete/export`; `reminder_set/list/cancel/snooze`; `fs_list/read/search/write/edit/move/delete/trash_list/undo`; `shell_run`; `web_fetch`. Each group has a switch under `[tools]`.
- **Filesystem:** tools act only on `ToolContext.resolved_paths` (what the policy resolved and classified). Critical paths (drive roots, home, FRIDAY's own folders, anything containing one) cannot be deleted or moved and are denied before a card is shown. Unsafe path shapes (UNC, device, alternate data streams, reserved names) are rejected before touching disk. Risky suffixes and persistence locations need T3. Deletes go to `<data>/trash` (30-day purge) with a signed undo journal. Atomic writes keep file mode.
- **Shell:** argv only, scrubbed env, timeout, output cap, process-tree kill; read-only allowlist is T2, everything else T3; batch files and bare names that resolve in the working folder are refused.
- **Web:** `fetch_pinned` connects to the IP the SSRF guard checked, verifies TLS against the host name, validates every redirect hop (max 5), uses identity encoding, caps size and time, extracts text from HTML. Output and errors are untrusted. The policy does syntactic URL checks only, with no DNS before approval.
- **Taint on stored rows:** tasks, notes and reminders written on a tainted turn are marked and come back as UNTRUSTED data.
- **SSRF guard:** judges IPv4 hidden in IPv6 (compat, NAT64, SIIT, Teredo, 6to4); blocks site-local.
- **CLI:** `friday show tasks|notes|reminders|trash`, read-only and daemon-independent.
- **Docs:** `ARCHITECTURE.md` (revision 4), `README.md`, `SECURITY.md`, `DEPLOYMENT.md`, `CONTRIBUTING.md`, `CHANGELOG.md` (0.2.0).

## Review

An independent adversarial review of the tranche found issues that were all fixed with regression tests in `tests/test_review_fixes.py` (critical-path ordering, risky-name judging on the resolved path, casefolded containment, IPv6-embedded addresses, taskkill tree walk, taint on stored rows, and others).

## Decisions made (veto-able)

- Default `fs_roots = ["~"]` per Alpha's choice. Narrow it in `config.toml` if that is too wide.
- Reminders only fire while the core runs. Autostart arrives in tranche 6.
- `note_update` with a new body is escalated to T2; `web_fetch` is always T2.

## Known limits

Worker threads can't be cancelled; background shell children survive a normal exit; ACLs and extended attributes are not preserved on rewrite; the Windows-specific paths (`taskkill`, reserved names, ADS) are covered by CI but untested by hand.

## Open items

- Run `friday run` on the device and try: add a task, set a reminder for two minutes ahead, list a folder, write and undo a file, fetch a page.
- CI has not run yet on Windows (needs the repo pushed to GitHub).
- Optional: add `[tools]` / `fs_roots` to `%APPDATA%\friday\config.toml` if the defaults need changing.
- Telegram (tranche 5) still needs a new BotFather token and Alpha's numeric Telegram user ID.

## Next

Tranche 3: sensors and voice (audio hub, double clap, wake phrase, STT, TTS), then UI, integrations and packaging.