"""Tests for the pre-model scope gate."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from autonomy.input_guardrail import InputGuardrail, build_input_guardrail, extract_scope_terms

SKILLS_DIR = Path("qsr-skills")


class InputGuardrailUnitTests(unittest.TestCase):
    def test_terms_are_derived_from_installed_skills(self):
        terms, descriptions = extract_scope_terms(SKILLS_DIR)
        for term in ("kiosk", "queue", "menu", "accuracy", "weather"):
            self.assertIn(term, terms)
        self.assertIn("accuracy", descriptions.lower())

    def test_keyword_match_skips_classifier(self):
        calls = []
        gate = InputGuardrail({"queue", "menu"}, lambda question: calls.append(question) or False)
        self.assertTrue(gate.is_allowed("How deep is the kiosk queue right now?"))
        self.assertEqual(calls, [])

    def test_classifier_blocks_out_of_scope_without_keyword(self):
        gate = InputGuardrail({"queue", "menu"}, lambda question: False)
        self.assertFalse(gate.is_allowed("What is the capital of India?"))

    def test_classifier_allows_in_scope_paraphrase(self):
        gate = InputGuardrail({"queue", "menu"}, lambda question: True)
        self.assertTrue(gate.is_allowed("Is it busy at the counter?"))

    def test_classifier_error_fails_open(self):
        gate = InputGuardrail({"queue"}, lambda question: None)
        self.assertTrue(gate.is_allowed("Ambiguous request with no known term"))

    def test_disabled_gate_allows_everything(self):
        gate = InputGuardrail(set(), lambda question: False, enabled=False)
        self.assertTrue(gate.is_allowed("What is the capital of India?"))

    def test_build_input_guardrail_respects_disable_flag(self):
        with patch.dict("os.environ", {"QSR_SCOPE_GATE": "false"}):
            gate = build_input_guardrail(SKILLS_DIR)
        self.assertFalse(gate.enabled)


class InputGuardrailHttpTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict("os.environ", {
            "QSR_AUTONOMY_DB": str(Path(self._tmp.name) / "state.db"),
            "QSR_AUTONOMY_MODULES": "",
            "QSR_WARMUP": "false",
        })
        self._env.start()
        spec = importlib.util.spec_from_file_location("qsr_scope_http_test", "operator-ui/app.py")
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)
        self.app.INPUT_GUARDRAIL = InputGuardrail(set(), lambda question: False)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.app.AUTONOMY.store.close()
        self._env.stop()
        self._tmp.cleanup()

    def test_out_of_scope_question_is_declined_before_model(self):
        request = urllib.request.Request(
            self.base + "/ask", data=json.dumps({"question": "What is the capital of India?"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with self.opener.open(request, timeout=3) as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["answer"], self.app.DECLINE_MESSAGE)

    def test_linked_event_does_not_bypass_the_gate(self):
        decision = {"event": {"service": "kiosk", "event_type": "queue_count_changed", "data": {"queue_count": 12}}}
        asked = []
        self.app.INPUT_GUARDRAIL = InputGuardrail(
            {"kiosk", "queue"}, lambda text: asked.append(text) or "replying to a kiosk" in text and "normal" in text)
        self.assertFalse(self.app.in_scope("What is the capital of India?", decision))
        self.assertTrue(self.app.in_scope("ok, back to normal", decision))
        self.assertFalse(self.app.in_scope("ok, back to normal", None))
        self.assertIn("Store operator replying to a kiosk queue_count_changed event: ok, back to normal", asked)


if __name__ == "__main__":
    unittest.main()
