# Security

FRIDAY has full access to the machine it runs on, so its security model is part of the product, not an
add-on. This page summarises that model and its known limits. The full design is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), section 6.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x (tranche 1) | Yes |

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately to the maintainer
(GitHub: `code8286`) with steps to reproduce, the version (`friday --version`), and your OS and Python
version. You should get a reply within 7 days. Never include real API keys or tokens in a report.

## Model

- **No prompt is a security boundary.** Every rule below is enforced in code. The persona text is a hint
  to the model and nothing more.
- **Trusted input** is only your typed input (console, and the desktop UI over its local token-protected
  socket in a later tranche), your voice inside an active voice session, and your allow-listed Telegram
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
- **Filesystem and network rules.** A denylist (SSH keys, browser profiles, credential stores, `.env`
  files, FRIDAY's own data directory) always needs T3. URL arguments pass an SSRF guard that blocks
  private and loopback ranges unless you allow them.

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
- Tranche 1 ships no filesystem, shell or web tools. When they arrive in tranche 2 they must act on the
  path the policy engine resolved, delete through the recycle bin, and pin fetches to the IPs the SSRF
  guard checked.

## Hardening checklist for a deployment

1. Install the keyring extra (`pip install "friday-assistant[secrets]"`, or `pip install keyring` when
   running from source). Without it the API key can only come from an environment variable, and the
   audit log is not keyed.
2. Store the key with `friday set-secret friday_api_key`. Never put it in `config.toml` or a script.
3. Keep `allowed_telegram_ids` limited to your own numeric ID once Telegram lands.
4. Leave `voice_t3_requires_challenge = true`.
5. Run `friday verify-audit` after updates, and whenever something looks off.
