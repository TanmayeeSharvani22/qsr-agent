from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from autonomy import hermes_gateway
from autonomy.hermes_gateway import GatewayError, HermesGateway, HermesSessions

KEY = "test-key-0123456789abcdef"


class FakeGateway(BaseHTTPRequestHandler):
    sessions: dict[str, list[dict]] = {}
    titles: set[str] = set()
    created = 0
    fail_turns = False

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        if self.headers.get("Authorization") == f"Bearer {KEY}":
            return True
        self._json(401, {"error": {"message": "Invalid gateway API key"}})
        return False

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._json(200, {"status": "ok"})
        if not self._authorized():
            return
        session_id = self.path.rsplit("/", 1)[-1]
        if session_id in self.sessions:
            return self._json(200, {"session": {"id": session_id}})
        self._json(404, {"error": {"message": "Session not found"}})

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path == "/api/sessions":
            if body.get("title") in self.titles:
                return self._json(400, {"error": {"message": "Title already in use"}})
            self.titles.add(body.get("title"))
            FakeGateway.created += 1
            session_id = f"api_{FakeGateway.created}"
            self.sessions[session_id] = []
            return self._json(201, {"session": {"id": session_id}})
        if self.path == "/v1/chat/completions":
            return self._json(200, {"choices": [{"message": {"content": "OK"}}]})
        session_id = self.path.split("/")[3]
        self.sessions[session_id].append(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if self.fail_turns:
            frames = [("error", {"message": "model unavailable"}), ("done", {})]
        else:
            # Context compression continues the conversation under a new id.
            rotated = session_id + "-2"
            self.sessions.setdefault(rotated, [])
            frames = [("run.started", {}), ("tool.started", {"tool_name": "kiosk.get_context", "args": {}}),
                      ("assistant.delta", {"delta": "Queue "}), ("assistant.delta", {"delta": "is 4."}),
                      ("assistant.completed", {"content": "Queue is 4.", "session_id": rotated}),
                      ("run.completed", {}), ("done", {})]
        self.wfile.write(b": keepalive\n\n")
        for name, data in frames:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())

    def log_message(self, *_args):
        pass


class HermesGatewayTests(unittest.TestCase):
    def setUp(self):
        FakeGateway.sessions, FakeGateway.titles, FakeGateway.fail_turns = {}, set(), False
        FakeGateway.created = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGateway)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.gateway = HermesGateway(KEY, self.url, timeout=5)
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def test_stream_chat_parses_events_and_sends_instructions(self):
        session_id = self.gateway.create_session("operator")
        events = list(self.gateway.stream_chat(session_id, "queue?", "be brief"))
        self.assertEqual([event["event"] for event in events],
                         ["run.started", "tool.started", "assistant.delta", "assistant.delta",
                          "assistant.completed", "run.completed", "done"])
        self.assertEqual(events[4]["content"], "Queue is 4.")
        self.assertEqual(FakeGateway.sessions[session_id][0], {"input": "queue?", "instructions": "be brief"})
        self.assertEqual(self.gateway.complete("warm up"), "OK")

    def test_failed_turn_bad_key_and_missing_key_raise_gateway_errors(self):
        session_id = self.gateway.create_session("operator")
        FakeGateway.fail_turns = True
        with self.assertRaisesRegex(GatewayError, "model unavailable"):
            list(self.gateway.stream_chat(session_id, "queue?"))
        with self.assertRaises(GatewayError) as caught:
            HermesGateway("wrong-key-0123456789", self.url, timeout=5).create_session("x")
        self.assertEqual(caught.exception.status, 401)
        with self.assertRaisesRegex(GatewayError, "not configured"):
            HermesGateway("", self.url).create_session("x")

    def test_sessions_persist_recreate_and_use_unique_titles(self):
        sessions = HermesSessions(self.home / "sessions.json")
        first = sessions.get("operator", self.gateway, "QSR operator chat")
        self.assertEqual(sessions.get("operator", self.gateway, "QSR operator chat"), first)
        self.assertEqual(HermesSessions(self.home / "sessions.json").get("operator", self.gateway, "x"), first)
        del FakeGateway.sessions[first]
        recreated = sessions.get("operator", self.gateway, "QSR operator chat")
        self.assertNotEqual(recreated, first)
        sessions.forget("operator")
        # Repeated "New chat" within the same minute must not collide on the title.
        self.assertNotEqual(sessions.get("operator", self.gateway, "QSR operator chat"), recreated)
        sessions.set("operator", "api_rotated")
        self.assertEqual(json.loads((self.home / "sessions.json").read_text())["operator"]["id"], "api_rotated")

    def test_idle_session_rotates_and_legacy_file_is_read(self):
        (self.home / "sessions.json").write_text(json.dumps({"operator": "api_legacy"}))
        FakeGateway.sessions["api_legacy"] = []
        sessions = HermesSessions(self.home / "sessions.json")
        self.assertEqual(sessions.get("operator", self.gateway, "chat", max_idle_seconds=600), "api_legacy")
        with patch("autonomy.hermes_gateway.time.time", return_value=time.time() + 601):
            fresh = sessions.get("operator", self.gateway, "chat", max_idle_seconds=600)
        self.assertNotEqual(fresh, "api_legacy")
        self.assertEqual(sessions.get("operator", self.gateway, "chat", max_idle_seconds=600), fresh)
        with patch("autonomy.hermes_gateway.time.time", return_value=time.time() + 10_000):
            self.assertEqual(sessions.get("operator", self.gateway, "chat"), fresh)  # 0 = never rotate

    def test_events_profile_key_is_read_from_profile_env(self):
        profile = self.home / "profiles" / hermes_gateway.EVENTS_PROFILE
        profile.mkdir(parents=True)
        (profile / ".env").write_text("OTHER=1\nAPI_SERVER_KEY=events-key-0123456789\n")
        with patch.dict("os.environ", {"HERMES_HOME": str(self.home)}):
            self.assertEqual(hermes_gateway.events_profile_key(), "events-key-0123456789")
            self.assertTrue(HermesGateway.events().base_url.endswith(f"/p/{hermes_gateway.EVENTS_PROFILE}"))

    def test_operator_chat_uses_one_persistent_session(self):
        with patch.dict("os.environ", {"QSR_AUTONOMY_DB": str(self.home / "state.db"), "QSR_AUTONOMY_MODULES": "",
                                       "QSR_WARMUP": "false", "QSR_LEARNING_DIR": str(self.home / "learning")}):
            spec = importlib.util.spec_from_file_location("qsr_chat_session_test", "operator-ui/app.py")
            app = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(app)
        try:
            with patch.object(app, "operator_gateway", return_value=self.gateway):
                self.assertEqual(app.ask_hermes("queue?"), {"ok": True, "answer": "Queue is 4."})
                self.assertTrue(app.ask_hermes("again?")["ok"])
                self.assertEqual(FakeGateway.created, 1)
                # The second turn follows the id Hermes reported after compression.
                self.assertEqual(FakeGateway.sessions["api_1-2"][0]["input"], "again?")
                app.new_chat()
                self.assertTrue(app.ask_hermes("fresh?")["ok"])
                self.assertEqual(FakeGateway.created, 2)
                FakeGateway.fail_turns = True
                self.assertEqual(app.ask_hermes("queue?"), {"ok": False, "error": "model unavailable"})
        finally:
            app.AUTONOMY.store.close()


if __name__ == "__main__":
    unittest.main()
