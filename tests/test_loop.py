# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

import asyncio

from friday.brain.messages import LLMResponse, TextBlock, check_pairing
from friday.core.errors import (
    AdmissionError,
    ProviderAuthError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderServerError,
    ProviderTimeout,
)
from friday.security.tiers import ConfirmChannel as CH
from tests.helpers import AsyncTempDirCase, calls, make_rig, say, use


def results_of(core):
    return [b for m in core.sessions.main().history for b in m.tool_results()]


class BasicTurnTests(AsyncTempDirCase):
    async def test_plain_answer_and_system_prompt(self):
        rig = await make_rig(self.tmp, [say("Hello, Alpha.")])
        res = await rig.core.submit("hi")
        self.assertEqual((res.status, res.text, res.llm_calls), ("ok", "Hello, Alpha.", 1))
        call = rig.provider.calls[0]
        self.assertIn("Live context", call["system"])
        self.assertEqual(len(call["tools"]), 9)  # all registered test tools are offered
        self.assertEqual(check_pairing(rig.core.sessions.main().history), [])
        await rig.core.stop()

    async def test_all_tool_calls_in_one_response_are_executed_and_answered(self):
        a, b, c = use("read_thing"), use("note_add", {"text": "milk"}), use("read_thing")
        rig = await make_rig(self.tmp, [calls(a, b, c), say("done")])
        res = await rig.core.submit("do three things")
        self.assertEqual(res.status, "ok")
        self.assertEqual([n for n, _ in rig.ran], ["read_thing", "note_add", "read_thing"])
        hist = rig.core.sessions.main().history
        self.assertEqual([r.tool_use_id for r in hist[2].tool_results()], [a.id, b.id, c.id])  # one message, same order
        self.assertEqual(check_pairing(hist), [])
        await rig.core.stop()

    async def test_unknown_tool_bad_args_and_crash_all_get_results_and_loop_continues(self):
        u1, u2, u3, u4 = use("rm_rf"), use("note_add", {"text": 5}), use("boom"), use("note_add", {"text": "x", "zzz": 1})
        rig = await make_rig(self.tmp, [calls(u1, u2, u3, u4), say("ok")])
        res = await rig.core.submit("go")
        self.assertEqual(res.status, "ok")
        rs = results_of(rig.core)
        self.assertEqual(len(rs), 4)
        self.assertTrue(all(r.is_error for r in rs))
        self.assertIn("Unknown tool", rs[0].content)
        self.assertIn("invalid arguments", rs[1].content)
        self.assertIn("RuntimeError", rs[2].content)
        self.assertNotIn("abcdef123456", rs[2].content)  # secret-looking value in the exception is redacted
        self.assertEqual(rig.ran, [])
        await rig.core.stop()

    async def test_tool_output_redacted_and_capped(self):
        rig = await make_rig(self.tmp, [calls(use("leaky")), say("ok")], mutate=lambda c: setattr(c.agent, "tool_output_max_chars", 25))
        await rig.core.submit("x")
        out = results_of(rig.core)[0].content
        self.assertNotIn("ABCDEFGHIJKLMNOPQRSTUV", out)
        self.assertNotIn("hunter2-secret", out)
        self.assertIn("[truncated", out)
        await rig.core.stop()


class ConfirmationFlowTests(AsyncTempDirCase):
    async def test_t2_denied_does_not_run(self):
        rig = await make_rig(self.tmp, [calls(use("send_msg", {"to": "bob", "body": "hi"})), say("ok, not sending")])
        seen = rig.auto_respond(False)
        res = await rig.core.submit("tell bob hi")
        self.assertEqual(res.status, "ok")
        self.assertEqual(rig.ran, [])
        self.assertIn("NOT APPROVED", results_of(rig.core)[0].content)
        self.assertIn("send_msg", seen[0]["card"])
        self.assertIn("'bob'", seen[0]["card"])
        await rig.core.stop()

    async def test_t2_approved_runs_exactly_once(self):
        rig = await make_rig(self.tmp, [calls(use("send_msg", {"to": "bob", "body": "hi"})), say("sent")])
        rig.auto_respond(True)
        await rig.core.submit("tell bob hi")
        self.assertEqual(rig.ran, [("send_msg", {"to": "bob", "body": "hi"})])
        self.assertTrue(rig.core.audit.verify().ok)
        events = [r.event for r in rig.core.audit.tail(40)]
        for needed in ("confirm.requested", "confirm.approved", "confirm.consumed", "tool.requested", "tool.finished"):
            self.assertIn(needed, events)
        await rig.core.stop()

    async def test_approval_timeout_is_a_denial(self):
        def short(c):
            c.security.confirm_ttl_s = 0.05
        rig = await make_rig(self.tmp, [calls(use("wipe")), say("fine")], mutate=short)
        res = await rig.core.submit("wipe it")  # nobody answers
        self.assertEqual(res.status, "ok")
        self.assertEqual(rig.ran, [])
        self.assertIn("timed out", results_of(rig.core)[0].content)
        await rig.core.stop()

    async def test_t3_voice_yes_is_not_enough_but_challenge_is(self):
        rig = await make_rig(self.tmp, [calls(use("wipe")), say("wiped")])
        outcomes = []

        def handler(ev):
            p = ev.payload
            outcomes.append(rig.core.respond_confirmation(p["id"], True, CH.VOICE, text="yes", voice_session_active=True, readback_confirmed=True).ok)
            outcomes.append(rig.core.respond_confirmation(p["id"], True, CH.VOICE, text=p["challenge"], voice_session_active=True).ok)

        rig.core.bus.on("confirm.requested", handler)
        await rig.core.submit("wipe")
        self.assertEqual(outcomes, [False, True])
        self.assertEqual([n for n, _ in rig.ran], ["wipe"])
        await rig.core.stop()

    async def test_flood_of_confirmations_is_refused_not_blocking(self):
        uses = [use("send_msg", {"to": str(i), "body": "x"}) for i in range(12)]
        rig = await make_rig(self.tmp, [calls(*uses), say("done")], mutate=lambda c: setattr(c.security, "confirm_ttl_s", 0.02))
        res = await rig.core.submit("spam")
        self.assertEqual(res.status, "ok")
        self.assertEqual(rig.ran, [])
        self.assertEqual(len(results_of(rig.core)), 12)
        await rig.core.stop()


class TaintTests(AsyncTempDirCase):
    async def test_untrusted_output_is_enveloped_and_cannot_break_out(self):
        rig = await make_rig(self.tmp, [calls(use("fetch_page")), say("summary")])
        await rig.core.submit("read the page")
        content = results_of(rig.core)[0].content
        self.assertTrue(content.startswith('<untrusted_data source="tool:fetch_page">'))
        self.assertEqual(content.count("</untrusted_data>"), 1)
        self.assertTrue(rig.core.sessions.main().is_tainted())
        await rig.core.stop()

    async def test_taint_in_same_batch_forces_confirmation_of_t1(self):
        rig = await make_rig(self.tmp, [calls(use("fetch_page"), use("note_add", {"text": "from page"})), say("ok")])
        seen = rig.auto_respond(False)
        await rig.core.submit("go")
        self.assertEqual([n for n, _ in rig.ran], ["fetch_page"])         # note_add did NOT auto-run
        self.assertEqual(len(seen), 1)
        self.assertIn("untrusted content", seen[0]["card"])
        await rig.core.stop()

    async def test_taint_persists_into_next_turn_until_trimmed(self):
        rig = await make_rig(self.tmp, [calls(use("fetch_page")), say("ok1"), calls(use("note_add", {"text": "n"})), say("ok2")])
        seen = rig.auto_respond(False)
        await rig.core.submit("read page")
        await rig.core.submit("now add a note")
        self.assertEqual(len(seen), 1)                                     # follow-up T1 write needed approval
        self.assertEqual([n for n, _ in rig.ran], ["fetch_page"])
        await rig.core.stop()

    async def test_clean_session_t1_runs_automatically(self):
        rig = await make_rig(self.tmp, [calls(use("note_add", {"text": "n"})), say("ok")])
        seen = rig.auto_respond(False)
        await rig.core.submit("add a note")
        self.assertEqual(seen, [])
        self.assertEqual([n for n, _ in rig.ran], ["note_add"])
        await rig.core.stop()

    async def test_large_untrusted_output_goes_through_quarantined_summarizer(self):
        rig = await make_rig(self.tmp, [calls(use("fetch_page")), say("final")], mutate=lambda c: setattr(c.agent, "summarize_untrusted_over_chars", 10))
        # The summarizer shares the core's provider: queue its reply between the two main replies.
        rig.provider.script.insert(1, LLMResponse([TextBlock("Neutral summary.")]))
        await rig.core.submit("read")
        content = results_of(rig.core)[0].content
        self.assertIn("Neutral summary.", content)
        self.assertNotIn("IGNORE ALL PREVIOUS", content)
        self.assertIn("+summarised", content)
        self.assertEqual(rig.provider.calls[1]["tools"], [])                # the summariser call had no tools
        await rig.core.stop()


class PolicyIntegrationTests(AsyncTempDirCase):
    async def test_workspace_create_auto_secret_path_needs_t3(self):
        ssh = self.tmp / "home" / ".ssh"
        ssh.mkdir(parents=True)
        rig = await make_rig(self.tmp, [
            calls(use("fs_write", {"path": "note.md", "content": "x"}), use("fs_write", {"path": str(ssh / "authorized_keys"), "content": "evil"})),
            say("done"),
        ])
        seen = rig.auto_respond(False)
        await rig.core.submit("write files")
        self.assertEqual([p["path"] for n, p in rig.ran], ["note.md"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["tier"], 3)
        self.assertIn("protected", seen[0]["card"])
        await rig.core.stop()

    async def test_private_url_is_hard_denied_without_asking(self):
        rig = await make_rig(self.tmp, [calls(use("web_get", {"url": "http://169.254.169.254/latest/meta-data"})), say("blocked")])
        seen = rig.auto_respond(True)  # even a willing approver is never asked
        await rig.core.submit("fetch")
        self.assertEqual(seen, [])
        self.assertEqual(rig.ran, [])
        self.assertIn("DENIED by policy", results_of(rig.core)[0].content)
        await rig.core.stop()


class LoopLimitTests(AsyncTempDirCase):
    async def test_iteration_cap_leaves_valid_history(self):
        script = [calls(use("read_thing")) for _ in range(20)]
        rig = await make_rig(self.tmp, script, mutate=lambda c: setattr(c.agent, "max_iterations", 3))
        res = await rig.core.submit("loop forever")
        self.assertEqual(res.status, "iteration_cap")
        self.assertEqual(res.llm_calls, 3)
        hist = rig.core.sessions.main().history
        self.assertEqual(check_pairing(hist), [])
        self.assertEqual(hist[-1].role, "assistant")
        rig.provider.script[:] = [say("next turn works")]
        self.assertEqual((await rig.core.submit("again")).status, "ok")
        self.assertEqual(check_pairing(rig.core.sessions.main().history), [])
        await rig.core.stop()

    async def test_tool_call_budget(self):
        uses = [use("read_thing") for _ in range(6)]
        rig = await make_rig(self.tmp, [calls(*uses), say("ok")], mutate=lambda c: setattr(c.agent, "max_tool_calls_per_turn", 2))
        await rig.core.submit("many")
        self.assertEqual(len(rig.ran), 2)
        rs = results_of(rig.core)
        self.assertEqual(len(rs), 6)
        self.assertIn("budget", rs[-1].content)
        await rig.core.stop()

    async def test_turn_timeout(self):
        async def slow(call):
            await asyncio.sleep(5)

        rig = await make_rig(self.tmp, [slow], mutate=lambda c: setattr(c.agent, "turn_timeout_s", 0.1))
        res = await rig.core.submit("hi")
        self.assertEqual(res.status, "timeout")
        self.assertEqual(check_pairing(rig.core.sessions.main().history), [])
        await rig.core.stop()


class RetryTests(AsyncTempDirCase):
    async def test_transient_errors_retry_with_backoff_then_succeed(self):
        rig = await make_rig(self.tmp, [ProviderTimeout("t"), ProviderServerError("5xx"), ProviderRateLimited("429", 0.03), say("finally")])
        res = await rig.core.submit("hi")
        self.assertEqual(res.text, "finally")
        self.assertEqual(len(rig.slept), 3)
        self.assertEqual(rig.slept[2], 0.03)                               # honours Retry-After (capped by llm_backoff_max_s)
        self.assertGreater(rig.slept[1], rig.slept[0] * 1.0 - 1e-9)        # exponential-ish growth
        await rig.core.stop()

    async def test_exhausted_retries_report_error_and_keep_history_valid(self):
        rig = await make_rig(self.tmp, [ProviderServerError("x")] * 5)
        res = await rig.core.submit("hi")
        self.assertEqual(res.status, "error")
        self.assertEqual(len(rig.provider.calls), 4)                      # 1 try + 3 retries
        self.assertEqual(check_pairing(rig.core.sessions.main().history), [])
        await rig.core.stop()

    async def test_auth_error_not_retried(self):
        rig = await make_rig(self.tmp, [ProviderAuthError("bad key"), say("never")])
        res = await rig.core.submit("hi")
        self.assertEqual(res.status, "error")
        self.assertIn("credentials", res.text)
        self.assertEqual(rig.slept, [])
        self.assertEqual(len(rig.provider.calls), 1)
        await rig.core.stop()

    async def test_failure_after_tool_results_still_valid(self):
        rig = await make_rig(self.tmp, [calls(use("read_thing")), ProviderProtocolError("garbled")])
        res = await rig.core.submit("hi")
        self.assertEqual(res.status, "error")
        hist = rig.core.sessions.main().history
        self.assertEqual(check_pairing(hist), [])
        self.assertEqual(hist[-1].role, "assistant")
        await rig.core.stop()


class KillSwitchTests(AsyncTempDirCase):
    async def test_kill_mid_tool_cancels_turn_and_history_stays_valid(self):
        rig = await make_rig(self.tmp, [calls(use("read_thing"), use("slow"), use("read_thing")), say("never")])
        started = asyncio.Event()

        @rig.core.registry.tool(name="slow", description="slow tool", schema={"type": "object", "properties": {}})
        async def slow(ctx):
            started.set()
            await asyncio.sleep(10)

        # re-offer the tool list: registry was extended after rig creation, the loop reads it per turn
        task = asyncio.create_task(rig.core.submit("go"))
        await asyncio.wait_for(started.wait(), 2)
        rig.core.trip_kill("test", "unit")
        res = await asyncio.wait_for(task, 2)
        self.assertEqual(res.status, "killed")
        hist = rig.core.sessions.main().history
        self.assertEqual(check_pairing(hist), [])
        self.assertEqual([n for n, _ in rig.ran], ["read_thing"])           # the 3rd call never ran
        # while tripped nothing runs and the provider is not called
        before = len(rig.provider.calls)
        res2 = await rig.core.submit("hello?")
        self.assertEqual(res2.status, "killed")
        self.assertEqual(len(rig.provider.calls), before)
        rig.core.reset_kill()
        rig.provider.script[:] = [say("back")]
        self.assertEqual((await rig.core.submit("ok")).text, "back")
        self.assertEqual(check_pairing(rig.core.sessions.main().history), [])
        await rig.core.stop()

    async def test_kill_cancels_pending_approval(self):
        rig = await make_rig(self.tmp, [calls(use("send_msg", {"to": "a", "body": "b"})), say("never")])
        got = asyncio.Event()
        rig.core.bus.on("confirm.requested", lambda ev: got.set())
        task = asyncio.create_task(rig.core.submit("send"))
        await asyncio.wait_for(got.wait(), 2)
        rig.core.trip_kill("panic", "unit")
        res = await asyncio.wait_for(task, 2)
        self.assertEqual(res.status, "killed")
        self.assertEqual(rig.ran, [])
        self.assertEqual(rig.core.broker.pending(), [])
        await rig.core.stop()

    async def test_kill_from_another_thread(self):
        import threading

        rig = await make_rig(self.tmp, [calls(use("send_msg", {"to": "a", "body": "b"})), say("never")])
        got = asyncio.Event()
        rig.core.bus.on("confirm.requested", lambda ev: got.set())
        task = asyncio.create_task(rig.core.submit("send"))
        await asyncio.wait_for(got.wait(), 2)
        threading.Thread(target=lambda: rig.core.trip_kill("hotkey", "thread")).start()
        res = await asyncio.wait_for(task, 2)
        self.assertEqual(res.status, "killed")
        await rig.core.stop()

    async def test_external_cancellation_propagates_and_no_orphaned_task_errors(self):
        loop = asyncio.get_running_loop()
        problems = []
        loop.set_exception_handler(lambda _loop, ctx: problems.append(ctx.get("message")))
        rig = await make_rig(self.tmp, [calls(use("slow2")), say("never")])
        started = asyncio.Event()

        @rig.core.registry.tool(name="slow2", description="slow", schema={"type": "object", "properties": {}})
        async def slow2(ctx):
            started.set()
            await asyncio.sleep(10)

        task = asyncio.create_task(rig.core.submit("go"))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(check_pairing(rig.core.sessions.main().history), [])
        self.assertFalse(rig.core.kill.tripped)
        # a subsequent turn works and the session lock was released
        rig.provider.script[:] = [say("still alive")]
        self.assertEqual((await rig.core.submit("hi")).text, "still alive")
        import gc
        gc.collect()
        await asyncio.sleep(0)
        self.assertEqual(problems, [])
        await rig.core.stop()


class HistoryTests(AsyncTempDirCase):
    async def test_trimming_between_turns_never_breaks_pairs_and_clears_taint(self):
        script = []
        for i in range(8):
            script += [calls(use("fetch_page") if i == 0 else use("read_thing")), say(f"a{i}")]
        rig = await make_rig(self.tmp, script, mutate=lambda c: (setattr(c.agent, "max_history_tokens", 120), setattr(c.agent, "keep_min_turns", 2)))
        for i in range(8):
            await rig.core.submit(f"question {i} " + "pad " * 40)
            self.assertEqual(check_pairing(rig.core.sessions.main().history), [], f"after turn {i}")
        s = rig.core.sessions.main()
        self.assertTrue(s.history[0].is_turn_start())
        self.assertFalse(s.is_tainted())                                    # the untrusted turn aged out of the window
        await rig.core.stop()

    async def test_on_trim_callback_receives_dropped_messages(self):
        rig = await make_rig(self.tmp, [say("a")] * 4, mutate=lambda c: (setattr(c.agent, "max_history_tokens", 50), setattr(c.agent, "keep_min_turns", 1)))
        dropped = []

        async def on_trim(session, msgs):
            dropped.extend(msgs)

        rig.core.loop.on_trim = on_trim
        for _ in range(4):
            await rig.core.submit("pad " * 60)
        self.assertTrue(dropped)
        await rig.core.stop()

    async def test_turns_are_serialised_per_session(self):
        order = []

        async def slow_reply(call):
            order.append("start")
            await asyncio.sleep(0.05)
            order.append("end")
            return say("x")

        rig = await make_rig(self.tmp, [slow_reply, slow_reply])
        await asyncio.gather(rig.core.submit("one"), rig.core.submit("two"))
        self.assertEqual(order, ["start", "end", "start", "end"])
        self.assertEqual(check_pairing(rig.core.sessions.main().history), [])
        await rig.core.stop()

    async def test_admission_gate_on_submit(self):
        rig = await make_rig(self.tmp, [say("x")])
        with self.assertRaises(AdmissionError):
            await rig.core.submit("hi", "telegram", 999)
        self.assertEqual(rig.provider.calls, [])
        await rig.core.stop()


class DaemonTests(AsyncTempDirCase):
    async def test_start_creates_files_and_verifies_audit(self):
        rig = await make_rig(self.tmp, [])
        core = rig.core
        self.assertTrue(core.cfg.db_path.exists())
        self.assertTrue(core.cfg.workspace.is_dir())
        self.assertGreaterEqual(len(core.ws_token), 32)
        self.assertEqual(core.degraded, [])
        self.assertTrue(core.audit.verify().ok)
        await core.stop()

    async def test_restart_with_keyed_audit_verifies_and_tamper_flags_degraded(self):
        from friday.core.daemon import FridayCore
        from friday.security.secrets import MemoryBackend, SecretStore
        from tests.helpers import make_cfg

        backend = MemoryBackend()
        cfg = make_cfg(self.tmp)
        core = FridayCore(cfg, secrets=SecretStore(backend))
        await core.start()
        await core.stop()
        core = FridayCore(cfg, secrets=SecretStore(backend))
        await core.start()
        self.assertEqual(core.degraded, [])
        self.assertTrue(core.audit.verify().ok)
        core.db.execute("DROP TRIGGER audit_no_update")
        core.db.execute("UPDATE audit SET actor='mallory' WHERE seq=1")
        await core.stop()
        core = FridayCore(cfg, secrets=SecretStore(backend))
        await core.start()
        self.assertTrue(any("audit log verification FAILED" in d for d in core.degraded))
        await core.stop()

    async def test_echo_provider_end_to_end_with_builtin_tool(self):
        from friday.core.daemon import FridayCore
        from tests.helpers import make_cfg

        core = FridayCore(make_cfg(self.tmp))
        await core.start()
        res = await core.submit("!tool get_time {}")
        self.assertEqual(res.status, "ok")
        self.assertIn("Tool results:", res.text)
        res = await core.submit("!tool list_tools {}")
        self.assertIn("get_time", res.text)
        await core.stop()

    async def test_console_channel_approval_roundtrip(self):
        import io
        import threading

        from friday.channels.console import ConsoleChannel
        rig = await make_rig(self.tmp, [calls(use("wipe")), say("wiped!")])
        core = rig.core
        out = io.StringIO()

        class FakeStdin:
            def __init__(self):
                self.q = []
                self.ev = threading.Event()

            def readline(self):
                while not self.q:
                    self.ev.wait(0.05)
                return self.q.pop(0)

        stdin = FakeStdin()
        chan = ConsoleChannel(core, stdin=stdin, out=out)
        runner = asyncio.create_task(chan.run())
        stdin.q.append("wipe everything\n")
        for _ in range(100):
            await asyncio.sleep(0.02)
            if core.broker.pending():
                break
        code = core.broker.pending()[0].short_code
        stdin.q.append("yes\n")            # not enough for T3
        await asyncio.sleep(0.2)
        self.assertEqual(rig.ran, [])
        stdin.q.append(code + "\n")
        for _ in range(100):
            await asyncio.sleep(0.02)
            if rig.ran:
                break
        self.assertEqual([n for n, _ in rig.ran], ["wipe"])
        stdin.q.append("/exit\n")
        await asyncio.wait_for(runner, 5)
        text = out.getvalue()
        self.assertIn("type the code", text)
        self.assertIn("friday> wiped!", text)
        await core.stop()
