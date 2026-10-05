# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""CLI:  python -m friday [run|init|set-secret|delete-secret|verify-audit|show-config|memory|check-provider]"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import getpass
import json
import logging
import sys

from .channels.console import ConsoleChannel
from .core.config import load_config
from .core.daemon import FridayCore
from .core.errors import FridayError
from .security.secrets import SecretStore


def _cfg_dict(cfg) -> dict:
    d = dataclasses.asdict(cfg)
    d["data_dir"] = str(cfg.data_dir)
    d["config_path"] = str(cfg.config_path)
    return d


async def _run(cfg) -> int:
    core = FridayCore(cfg)
    await core.start()
    if core.degraded:
        print("[degraded] " + "; ".join(core.degraded), file=sys.stderr)
    for note in cfg.notes:
        print("[note] " + note, file=sys.stderr)
    try:
        await ConsoleChannel(core).run()
    finally:
        await core.stop()
    return 0


async def _check_provider(cfg) -> int:
    """Live smoke test of the configured provider: plain reply, then a native tool call. Never prints the key."""
    from .brain.messages import user_text
    from .brain.provider import FridayProvider, build_auth
    from .core.errors import ProviderError

    pc = cfg.provider
    if pc.kind != "friday":
        print(f"provider.kind is not 'friday' (it is {pc.kind!r}); set kind = \"friday\" in config.toml first.")
        return 1
    secrets = SecretStore()
    prov = FridayProvider(pc, build_auth(pc, secrets))
    print(f"POST {pc.base_url.rstrip('/')}/{pc.path.lstrip('/')}  model={pc.model}  codec={pc.codec}  auth={pc.auth_scheme}")
    tools = [{"name": "get_weather", "description": "Get weather for a city",
              "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}]
    try:
        r = await prov.complete(system="You are a terse assistant.", messages=[user_text("Say hi in five words.")], tools=[], max_tokens=pc.max_tokens)
        print(f"[1] plain  -> {r.stop_reason}: {r.text!r}  (tokens in/out {r.usage.input_tokens}/{r.usage.output_tokens})")
        r = await prov.complete(system="Use tools when asked.", messages=[user_text("What's the weather in Chennai? Use the tool.")], tools=tools, max_tokens=pc.max_tokens)
        calls = [(u.name, u.arguments) for u in r.tool_uses()]
        print(f"[2] tools  -> {r.stop_reason}: {calls or r.text!r}")
        ok = bool(calls)
    except ProviderError as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 2
    print("OK" if ok else "reachable, but the model did not call the tool (try tool_mode = \"json\" or another model)")
    return 0 if ok else 3


def _memory_cmd(cfg, args) -> int:
    """Inspect / edit FRIDAY's built-in memory offline (no model, no daemon needed)."""
    from datetime import datetime

    from .core.db import Database
    from .memory.engine import MemoryEngine, MemoryRejected
    from .memory.store import MemoryStore

    db = Database(cfg.db_path).open()
    try:
        eng = MemoryEngine(MemoryStore(db), cfg.memory, use_model=False)
        eng.store.init()
        act = args.action
        if act == "list":
            rows = eng.store.recent(args.n)
            for m in rows:
                print(f"#{m.id} [{m.kind}{', pinned' if m.pinned else ''}] {m.text}  ({datetime.fromtimestamp(m.created_at):%Y-%m-%d}, {m.provenance})")
            print(f"{eng.store.count()} memories total")
        elif act == "search":
            for m in eng.recall(" ".join(args.rest) or "", args.n):
                print(f"#{m.id} [{m.kind}] {m.text}")
        elif act == "forget":
            print("forgotten." if args.rest and eng.forget(int(args.rest[0])) else "no such memory.")
        elif act == "pin":
            print("pinned." if args.rest and eng.store.set_pinned(int(args.rest[0]), True) else "no such memory.")
        elif act == "unpin":
            print("unpinned." if args.rest and eng.store.set_pinned(int(args.rest[0]), False) else "no such memory.")
        elif act == "add":
            try:
                mid, created = eng.remember(" ".join(args.rest), provenance="user", source="cli", importance=0.8, pinned=args.pin)
            except MemoryRejected as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 1
            print(f"saved #{mid}." if created else f"already stored as #{mid}.")
        elif act == "summary":
            print(eng.store.get_summary("main") or "(no summary yet)")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    from . import __version__

    ap = argparse.ArgumentParser(prog="friday", description="F.R.I.D.A.Y. — headless core (tranche 1)")
    ap.add_argument("--version", action="version", version=f"friday {__version__}")
    ap.add_argument("--config", help="path to config.toml")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run", help="start the headless core with the console channel (default)")
    sub.add_parser("init", help="write a default config.toml if missing and print its path")
    p = sub.add_parser("set-secret", help="store a secret in the OS keyring")
    p.add_argument("name")
    p = sub.add_parser("delete-secret", help="remove a secret from the OS keyring")
    p.add_argument("name")
    sub.add_parser("verify-audit", help="verify the audit log hash chain")
    sub.add_parser("check-provider", help="live-test the configured model endpoint (plain reply + tool call)")
    sub.add_parser("show-config", help="print the effective configuration")
    p = sub.add_parser("memory", help="inspect or edit built-in memory: list|search|add|forget|pin|unpin|summary")
    p.add_argument("action", choices=["list", "search", "add", "forget", "pin", "unpin", "summary"])
    p.add_argument("rest", nargs="*", help="query / text / id")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--pin", action="store_true", help="with add: always include this memory in context")
    args = ap.parse_args(argv)
    cmd = args.cmd or "run"

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        cfg = load_config(args.config)
        if cmd == "init":
            print(cfg.config_path)
            return 0
        if cmd == "show-config":
            print(json.dumps(_cfg_dict(cfg), indent=2))
            return 0
        if cmd == "set-secret":
            value = getpass.getpass(f"value for {args.name} (input hidden): ")
            SecretStore().set(args.name, value)
            print("stored.")
            return 0
        if cmd == "delete-secret":
            SecretStore().delete(args.name)
            print("deleted.")
            return 0
        if cmd == "check-provider":
            return asyncio.run(_check_provider(cfg))
        if cmd == "memory":
            return _memory_cmd(cfg, args)
        if cmd == "verify-audit":
            core = FridayCore(cfg)
            core.db.open()
            key = core.secrets.audit_hmac_key(create=False) if core.db.kv_get("audit.keyed") == "1" else None
            core.audit._key = key
            res = core.audit.verify()
            print(f"{'OK' if res.ok else 'FAILED: ' + str(res.error)} ({res.records} records)")
            return 0 if res.ok else 2
        return asyncio.run(_run(cfg))
    except FridayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
