# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Real-socket test of the stdlib transport against a throwaway local HTTP server."""

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from friday.brain.messages import user_text
from friday.brain.provider import BearerAuth, FridayProvider
from friday.core.config import ProviderConfig
from friday.core.errors import ProviderAuthError, ProviderConnectionError, ProviderTimeout


class _Handler(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if self.path.startswith("/slow"):
            time.sleep(1.0)
        if self.headers.get("Authorization") != "Bearer good-key":
            self.send_response(401)
            self.end_headers()
            return
        out = json.dumps({"content": [{"type": "text", "text": "pong"}], "usage": {"input_tokens": 1, "output_tokens": 2}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        try:
            self.wfile.write(out)
        except BrokenPipeError:  # client gave up (timeout test)
            pass


class UrllibTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _Handler.seen = []
        self.srv = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def provider(self, key="good-key", **kw):
        cfg = ProviderConfig(kind="friday", base_url=f"http://127.0.0.1:{self.port}", path="/v1/chat", codec="messages", timeout_s=kw.pop("timeout_s", 5), **kw)
        return FridayProvider(cfg, BearerAuth(lambda: key))

    async def test_round_trip(self):
        resp = await self.provider().complete(system="s", messages=[user_text("ping")], tools=[])
        self.assertEqual(resp.text, "pong")
        self.assertEqual(resp.usage.output_tokens, 2)
        self.assertEqual(_Handler.seen[0]["auth"], "Bearer good-key")
        self.assertEqual(_Handler.seen[0]["body"]["model"], "auto/best-reasoning")

    async def test_auth_failure_maps_to_typed_error(self):
        with self.assertRaises(ProviderAuthError):
            await self.provider(key="wrong").complete(system="s", messages=[user_text("x")], tools=[])

    async def test_connection_refused_and_timeout(self):
        dead = FridayProvider(ProviderConfig(kind="friday", base_url="http://127.0.0.1:9", codec="messages", timeout_s=2), BearerAuth(lambda: "k"))
        with self.assertRaises(ProviderConnectionError):
            await dead.complete(system="s", messages=[user_text("x")], tools=[])
        cfg = ProviderConfig(kind="friday", base_url=f"http://127.0.0.1:{self.port}", path="/slow", codec="messages", timeout_s=0.2)
        with self.assertRaises(ProviderTimeout):
            await FridayProvider(cfg, BearerAuth(lambda: "good-key")).complete(system="s", messages=[user_text("x")], tools=[])


if __name__ == "__main__":
    unittest.main()
