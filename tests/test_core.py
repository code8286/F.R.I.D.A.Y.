# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

import os
import threading
import unittest
from pathlib import Path
from unittest import mock

from friday.brain.messages import Message, TextBlock, ToolResultBlock, ToolUseBlock, check_pairing, user_text
from friday.core.audit import AuditLog
from friday.core.bus import EventBus
from friday.core.config import DEFAULT_CONFIG_TOML, SecurityConfig, load_config
from friday.core.db import MIGRATIONS, Database
from friday.core.errors import AdmissionError, ConfigError, KillSwitchTripped, StorageError
from friday.core.killswitch import KillSwitch
from friday.core.schema import check_schema, validate
from friday.core.session import Session, SessionManager
from tests.helpers import AsyncTempDirCase, TempDirCase


class ConfigTests(TempDirCase):
    def test_defaults_write_file_and_memory_is_builtin(self):
        with mock.patch.dict(os.environ, {"FRIDAY_DATA_DIR": str(self.tmp)}, clear=False):
            cfg = load_config()
        self.assertTrue((self.tmp / "config.toml").exists())
        self.assertTrue(cfg.memory.enabled)
        self.assertFalse(hasattr(cfg, "hermes"))
        self.assertEqual(cfg.provider.model, "auto/best-reasoning")
        self.assertEqual(cfg.provider.kind, "echo")
        self.assertEqual(cfg.notes, [])

    def test_first_run_applies_the_written_default_file(self):
        with mock.patch.dict(os.environ, {"FRIDAY_DATA_DIR": str(self.tmp)}, clear=False):
            first = load_config()
            second = load_config()
        self.assertEqual(first.provider, second.provider)
        self.assertEqual(first.provider.base_url, "http://localhost:20128")
        self.assertEqual(first.provider.codec, "openai")

    def test_example_config_matches_the_written_default(self):
        example = Path(__file__).resolve().parent.parent / "config.example.toml"
        self.assertEqual(example.read_text(encoding="utf-8"), DEFAULT_CONFIG_TOML)

    def test_default_toml_parses_and_validates(self):
        p = self.tmp / "c.toml"
        p.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
        cfg = load_config(p)
        self.assertEqual(cfg.security.confirm_ttl_s, 60)

    def test_legacy_hermes_section_is_ignored_with_a_note(self):
        p = self.tmp / "c.toml"
        p.write_text('[hermes]\nbackend = "auto"\ncli_path = "C:\\\\tools\\\\hermes.exe"\n[conversation]\nuser_name = "Zed"\n', encoding="utf-8")
        cfg = load_config(p)
        self.assertEqual(cfg.conversation.user_name, "Zed")
        self.assertEqual(len(cfg.notes), 1)
        self.assertIn("hermes", cfg.notes[0])

    def test_memory_section_and_ranges(self):
        p = self.tmp / "c.toml"
        p.write_text('[memory]\nrecall_k = 3\nuse_model = false\n', encoding="utf-8")
        cfg = load_config(p)
        self.assertEqual(cfg.memory.recall_k, 3)
        self.assertFalse(cfg.memory.use_model)
        p.write_text('[memory]\nmax_fact_chars = 5\n', encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_config(p)

    def test_rejects_unknown_keys_and_bad_values(self):
        p = self.tmp / "c.toml"
        for body in ['[memory]\nnope = 1\n', '[wat]\nx = 1\n', '[agent]\nmax_iterations = "ten"\n',
                     '[provider]\nauth_scheme = "magic"\n', '[provider]\nkind = "friday"\nbase_url = ""\n']:
            p.write_text(body, encoding="utf-8")
            with self.assertRaises(ConfigError, msg=body):
                load_config(p)


class DbTests(TempDirCase):
    def test_wal_migrations_and_kv(self):
        db = Database(self.tmp / "x.db").open()
        self.assertEqual(db.scalar("PRAGMA journal_mode").lower(), "wal")
        self.assertEqual(db.scalar("PRAGMA user_version"), len(MIGRATIONS))
        db.kv_set("a", "1", 1.0)
        db.kv_set("a", "2", 2.0)
        self.assertEqual(db.kv_get("a"), "2")
        db.close()
        db2 = Database(self.tmp / "x.db").open()  # reopen: migrations are idempotent
        self.assertEqual(db2.kv_get("a"), "2")
        db2.close()

    def test_transaction_rolls_back(self):
        db = Database(":memory:").open()
        self.addCleanup(db.close)
        with self.assertRaises(ValueError), db.transaction():
            db.kv_set("k", "v", 1.0)
            raise ValueError("boom")
        self.assertIsNone(db.kv_get("k"))

    def test_newer_schema_refused(self):
        db = Database(self.tmp / "y.db").open()
        db.execute("PRAGMA user_version=99")
        db.close()
        with self.assertRaises(StorageError):
            Database(self.tmp / "y.db").open()


class AuditTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.db = Database(":memory:").open()
        self.addCleanup(self.db.close)

    def test_chain_verifies(self):
        log = AuditLog(self.db)
        for i in range(5):
            log.append("t", "e", {"i": i})
        self.assertTrue(log.verify().ok)
        self.assertEqual(log.verify().records, 5)

    def test_triggers_block_update_and_delete(self):
        log = AuditLog(self.db)
        log.append("t", "e")
        with self.assertRaises(StorageError):
            self.db.execute("UPDATE audit SET actor='x'")
        with self.assertRaises(StorageError):
            self.db.execute("DELETE FROM audit")

    def test_tamper_detected_even_without_triggers(self):
        log = AuditLog(self.db)
        for i in range(4):
            log.append("t", "e", {"i": i})
        self.db.execute("DROP TRIGGER audit_no_update")
        self.db.execute("UPDATE audit SET data='{\"i\":99}' WHERE seq=2")
        res = log.verify()
        self.assertFalse(res.ok)
        self.assertEqual(res.bad_seq, 2)

    def test_truncation_and_gap_detected(self):
        log = AuditLog(self.db)
        for i in range(4):
            log.append("t", "e", {"i": i})
        self.db.execute("DROP TRIGGER audit_no_delete")
        self.db.execute("DELETE FROM audit WHERE seq=4")
        self.assertFalse(log.verify().ok)  # tail anchor
        log2 = AuditLog(Database(":memory:").open())
        self.addCleanup(log2.db.close)
        for _ in range(4):
            log2.append("t", "e")
        log2.db.execute("DROP TRIGGER audit_no_delete")
        log2.db.execute("DELETE FROM audit WHERE seq=2")
        self.assertIn("gap", log2.verify().error)

    def test_hmac_key_blocks_full_rewrite(self):
        log = AuditLog(self.db, hmac_key=b"k" * 32)
        log.append("t", "e", {"a": 1})
        self.assertTrue(log.verify().ok)
        self.assertFalse(AuditLog(self.db).verify().ok)               # wrong (no) key
        self.assertFalse(AuditLog(self.db, hmac_key=b"z" * 32).verify().ok)

    def test_redaction_hook_applies(self):
        log = AuditLog(self.db, redact=lambda d: {k: "[R]" for k in d})
        rec = log.append("t", "e", {"secret": "s3cret"})
        self.assertEqual(rec.data, {"secret": "[R]"})

    def test_concurrent_appends_stay_consistent(self):
        log = AuditLog(self.db)

        def work(n):
            for i in range(25):
                log.append(f"w{n}", "e", {"i": i})

        threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        res = log.verify()
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.records, 150)


class SchemaTests(unittest.TestCase):
    S = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 5},
            "n": {"type": "integer", "minimum": 1, "maximum": 3},
            "p": {"enum": ["low", "high"]},
            "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
        },
        "required": ["title"],
        "additionalProperties": False,
    }

    def test_valid(self):
        self.assertEqual(validate({"title": "ok", "n": 2, "p": "low", "tags": ["a"]}, self.S), [])

    def test_errors(self):
        for bad in [{}, {"title": ""}, {"title": "toolong"}, {"title": "a", "n": 0}, {"title": "a", "n": True},
                    {"title": "a", "n": 1.5}, {"title": "a", "p": "mid"}, {"title": "a", "tags": [1]},
                    {"title": "a", "tags": ["a", "b", "c"]}, {"title": "a", "extra": 1}, "str", []]:
            self.assertTrue(validate(bad, self.S), bad)

    def test_check_schema_rejects_malformed(self):
        for bad in [{"type": "wat"}, {"type": "object", "required": ["x"]}, {"properties": []}, {"pattern": "("}]:
            with self.assertRaises(ValueError):
                check_schema(bad)


class BusTests(AsyncTempDirCase):
    async def test_pattern_subscription_and_drop_oldest(self):
        bus = EventBus()
        sub = bus.subscribe("confirm.*", maxsize=2)
        other = bus.subscribe("turn.*")
        for i in range(4):
            bus.publish("confirm.requested", {"i": i})
        bus.publish("turn.started", {})
        self.assertEqual(sub.dropped, 2)
        self.assertEqual((await sub.get(0.1)).payload["i"], 2)
        self.assertEqual((await other.get(0.1)).topic, "turn.started")

    async def test_broken_callback_does_not_break_publisher(self):
        bus = EventBus()
        bus.on("x", lambda ev: 1 / 0)
        bus.publish("x", {})  # no exception

    async def test_threadsafe_publish(self):

        bus = EventBus()
        bus.bind_loop()
        sub = bus.subscribe("t.*")
        threading.Thread(target=lambda: bus.publish_threadsafe("t.x", {"v": 1})).start()
        self.assertEqual((await sub.get(1)).payload["v"], 1)


class KillSwitchTests(TempDirCase):
    def test_trip_reset_hooks_and_audit(self):
        db = Database(":memory:").open()
        self.addCleanup(db.close)
        audit = AuditLog(db)
        bus = EventBus()
        ks = KillSwitch(bus, audit)
        hits = []
        ks.on_trip(lambda: hits.append(1))
        ks.check()
        ks.trip("because", "test")
        ks.trip("again", "test")  # idempotent: hook + audit fire once
        self.assertEqual(hits, [1])
        with self.assertRaises(KillSwitchTripped):
            ks.check()
        ks.reset("me")
        ks.check()
        events = [r.event for r in audit.tail()]
        self.assertEqual(events, ["kill.tripped", "kill.reset"])


class SessionTests(unittest.TestCase):
    def _turn(self, s, text, tools=0, tainted=False):
        s.append(user_text(text))
        for i in range(tools):
            tid = f"{text}-{i}"
            s.append(Message("assistant", [ToolUseBlock(tid, "t", {})]))
            s.append(Message("user", [ToolResultBlock(tid, "x" * 400)], {"tainted": tainted}))
        s.append(Message("assistant", [TextBlock("done " + "y" * 400)]))

    def test_trim_drops_whole_turns_and_keeps_pairing_valid(self):
        s = Session()
        for i in range(6):
            self._turn(s, f"q{i}", tools=2)
        before = len(s.history)
        dropped = s.trim(max_tokens=600, keep_min_turns=2)
        self.assertTrue(dropped)
        self.assertLess(len(s.history), before)
        self.assertEqual(check_pairing(s.history), [])
        self.assertTrue(s.history[0].is_turn_start())
        self.assertGreaterEqual(len(s.turn_starts()), 2)

    def test_trim_never_drops_below_min_turns(self):
        s = Session()
        for i in range(3):
            self._turn(s, f"q{i}", tools=1)
        s.trim(max_tokens=1, keep_min_turns=2)
        self.assertEqual(len(s.turn_starts()), 2)

    def test_taint_clears_when_tainted_content_trimmed(self):
        s = Session()
        self._turn(s, "old", tools=1, tainted=True)
        self._turn(s, "mid", tools=1)
        self._turn(s, "new", tools=1)
        self.assertTrue(s.is_tainted())
        s.trim(max_tokens=450, keep_min_turns=2)
        self.assertFalse(s.is_tainted())

    def test_check_pairing_flags_problems(self):
        bad = [user_text("a"), Message("assistant", [ToolUseBlock("1", "t", {})]), user_text("b")]
        self.assertTrue(check_pairing(bad))
        orphan = [user_text("a"), Message("assistant", [TextBlock("x")]), Message("user", [ToolResultBlock("9", "r")])]
        self.assertTrue(check_pairing(orphan))


class AdmissionTests(unittest.TestCase):
    def test_rules(self):
        cfg = SecurityConfig()
        cfg.allowed_telegram_ids = [42]
        sm = SessionManager(cfg)
        self.assertEqual(sm.admit("console").channel, "console")
        self.assertEqual(sm.admit("ui").channel, "ui")
        self.assertEqual(sm.admit("telegram", 42).principal, 42)
        for ch, pr, va in [("telegram", 7, False), ("telegram", None, False), ("voice", None, False), ("irc", 1, False)]:
            with self.assertRaises(AdmissionError):
                sm.admit(ch, pr, voice_session_active=va)
        self.assertEqual(sm.admit("voice", voice_session_active=True).channel, "voice")
        with self.assertRaises(AdmissionError):
            SessionManager(SecurityConfig()).admit("telegram", 42)  # empty allow-list refuses everyone


if __name__ == "__main__":
    unittest.main()
