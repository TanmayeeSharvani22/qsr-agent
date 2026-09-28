from __future__ import annotations

import json
import importlib.util
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from autonomy.advisor import HermesRunner
from autonomy.event_agent import Capability, CapabilityCatalog, HermesEventAgent, Skill, StaleContextError, parse_event_response
from autonomy.registry import AutonomyRegistry
from autonomy.service_capabilities import validate_menu, validate_remake
from autonomy.store import ProposalStore
from autonomy.worker import build_controller


class FakeService:
    def __init__(self):
        self.calls = []

    def list_tools(self):
        return [
            {"name": "context", "inputSchema": {"type": "object", "additionalProperties": False}},
            {"name": "remake", "inputSchema": {
                "type": "object", "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"], "additionalProperties": False}},
        ]

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"restaurant": {"id": "qsr-001"}, "executed": True}


class ScriptedHermes:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return json.dumps(next(self.responses))


class EventAgentTests(unittest.TestCase):
    def test_http_accepts_events_without_waiting_for_hermes(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingRunner:
            def complete(self, prompt):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test worker was not released")
                return json.dumps({"summary": "No change", "action": None})

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "QSR_AUTONOMY_DB": str(Path(directory) / "state.db"),
            "QSR_AUTONOMY_MODULES": "",
        }):
            spec = importlib.util.spec_from_file_location("qsr_queue_http_test", "operator-ui/app.py")
            app = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(app)
            app.AUTONOMY.store.close()
            store = ProposalStore(Path(directory) / "http.db")
            registry = AutonomyRegistry()
            registry.register_event(HermesEventAgent(BlockingRunner(), self.catalog))
            app.AUTONOMY = registry.build(store)
            server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base = f"http://127.0.0.1:{server.server_port}"
            app.AUTONOMY.start()
            server_thread.start()
            try:
                for event_id in ("http-first", "http-second", "http-second"):
                    request = urllib.request.Request(
                        base + "/autonomy/events",
                        data=json.dumps({**self.event, "event_id": event_id}).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    with opener.open(request, timeout=2) as response:
                        self.assertEqual(response.status, 202)
                        payload = json.load(response)
                    self.assertEqual(payload["status"], "queued")
                    self.assertNotIn("proposal", payload)
                    self.assertTrue(entered.wait(2))
                self.assertTrue(payload["duplicate"])
                with opener.open(base + "/autonomy/status", timeout=2) as response:
                    self.assertEqual(json.load(response)["queue"], {"queued": 1, "processing": 1})
            finally:
                release.set()
                server.shutdown()
                server_thread.join()
                server.server_close()
                app.AUTONOMY.stop()
                store.close()

    def test_queue_recovers_interrupted_and_waiting_events_in_order(self):
        completed = threading.Event()
        calls = []

        class RecoveryRunner:
            def complete(self, prompt):
                calls.append(prompt)
                if len(calls) == 2:
                    completed.set()
                return json.dumps({"summary": "Recovered", "action": None})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.db"
            store = ProposalStore(path)
            store.enqueue_event(self.event)
            store.enqueue_event({**self.event, "event_id": "waiting"})
            self.assertEqual(store.claim_event()["event_id"], self.event["event_id"])
            store.close()
            store = ProposalStore(path)
            registry = AutonomyRegistry()
            registry.register_event(HermesEventAgent(RecoveryRunner(), self.catalog))
            controller = registry.build(store)
            controller.start()
            try:
                self.assertTrue(completed.wait(2))
            finally:
                controller.stop()
            self.assertIn('"event_id":"test-1"', calls[0])
            self.assertIn('"event_id":"waiting"', calls[1])
            self.assertTrue(controller.enqueue_event(self.event)["duplicate"])
            self.assertEqual(store.queue_status(), {"queued": 0, "processing": 0})
            store.close()

    def test_failed_queued_event_does_not_block_next_and_can_retry(self):
        completed = threading.Event()
        calls = []

        class FailingRunner:
            def complete(self, prompt):
                calls.append(prompt)
                if len(calls) == 1:
                    raise RuntimeError("service unavailable")
                completed.set()
                return json.dumps({"summary": "No change", "action": None})

        with tempfile.TemporaryDirectory() as directory:
            store = ProposalStore(Path(directory) / "state.db")
            registry = AutonomyRegistry()
            registry.register_event(HermesEventAgent(FailingRunner(), self.catalog))
            controller = registry.build(store)
            controller.enqueue_event(self.event)
            controller.enqueue_event({**self.event, "event_id": "next"})
            controller.start()
            try:
                self.assertTrue(completed.wait(2))
            finally:
                controller.stop()
            decisions = {item["event"]["event_id"]: item for item in store.decisions()}
            self.assertEqual(decisions["test-1"]["status"], "failed")
            self.assertEqual(decisions["next"]["status"], "no_action")
            self.assertFalse(controller.enqueue_event(self.event)["duplicate"])
            completed.clear()
            controller.start()
            try:
                self.assertTrue(completed.wait(2))
            finally:
                controller.stop()
            self.assertEqual(store.decisions()[0]["status"], "no_action")
            store.close()

    def test_queue_returns_while_hermes_is_blocked_and_runs_fifo(self):
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = []

        class BlockingRunner:
            def complete(self, prompt):
                calls.append(prompt)
                if len(calls) == 1:
                    entered.set()
                    if not release.wait(5):
                        raise RuntimeError("test worker was not released")
                else:
                    finished.set()
                return json.dumps({"summary": "No change", "action": None})

        with tempfile.TemporaryDirectory() as directory:
            store = ProposalStore(Path(directory) / "state.db")
            registry = AutonomyRegistry()
            registry.register_event(HermesEventAgent(BlockingRunner(), self.catalog))
            controller = registry.build(store)
            controller.start()
            try:
                self.assertEqual(controller.enqueue_event(self.event)["status"], "queued")
                self.assertTrue(entered.wait(2))
                self.assertTrue(controller.enqueue_event(self.event)["duplicate"])
                second = {**self.event, "event_id": "second-event"}
                self.assertEqual(controller.enqueue_event(second)["status"], "queued")
                self.assertEqual(controller.status()["queue"], {"queued": 1, "processing": 1})
                self.assertEqual(len(calls), 1)
                release.set()
                self.assertTrue(finished.wait(2))
            finally:
                release.set()
                controller.stop()
            self.assertEqual(controller.status()["queue"], {"queued": 0, "processing": 0})
            self.assertIn('"event_id":"test-1"', calls[0])
            self.assertIn('"event_id":"second-event"', calls[1])
            self.assertEqual({item["status"] for item in store.decisions()}, {"no_action"})
            store.close()

    def test_runner_does_not_use_empty_toolset_fallback(self):
        with patch("autonomy.advisor.subprocess.Popen") as popen:
            popen.return_value.communicate.return_value = ('{"action":null}', "")
            popen.return_value.returncode = 0
            runner = HermesRunner()
            runner.hermes = "/bin/true"
            runner.complete("test")
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--toolsets") + 1], "context_engine")
        self.assertEqual(popen.call_args.kwargs["env"]["HERMES_IGNORE_RULES"], "1")

    def setUp(self):
        self.service = FakeService()
        self.catalog = CapabilityCatalog()
        self.catalog.register_tool(Capability("accuracy.context", "Read accuracy", self.service, "context", True))
        self.catalog.register_tool(Capability(
            "accuracy.remake", "Remake order", self.service, "remake", False,
            ("accuracy.context",), lambda arguments, observations: None,
        ))
        self.catalog.register_skill(Skill(
            "accuracy", "Handle mismatches", Path("qsr-skills/order-accuracy/SKILL.md"),
            ("accuracy.context", "accuracy.remake"),
        ))
        self.event = {"event_id": "test-1", "event_type": "new_owner_event", "data": {"order_id": "ORD-1042"}}
        self.read = {"skills": ["accuracy"], "reads": [{"tool": "accuracy.context", "arguments": {}}]}
        self.action = {"summary": "Remake flagged order", "action": {
            "tool": "accuracy.remake", "arguments": {"order_id": "ORD-1042"}}}

    def test_model_selects_skill_read_and_non_menu_action(self):
        runner = ScriptedHermes(self.read, self.action)
        agent = HermesEventAgent(runner, self.catalog)
        progress = []
        agent.report_progress = progress.append
        evaluation = agent.evaluate_event(self.event, False)
        self.assertEqual([item["round"] for item in progress], [1, 2])
        self.assertEqual(progress[0]["stage"], "Choosing relevant guidance")
        self.assertEqual(progress[1]["stage"], "Reviewing store evidence")
        self.assertEqual(evaluation.proposal.tool, "accuracy.remake")
        self.assertEqual(evaluation.decision["skills"], ["accuracy"])
        self.assertEqual(self.service.calls, [("context", {})])
        self.assertIn("Use the Order Accuracy MCP", runner.prompts[1])
        result = agent.execute_approved({
            "evidence": evaluation.proposal.evidence, "tool": evaluation.proposal.tool,
            "arguments": evaluation.proposal.arguments,
        })
        self.assertTrue(result["executed"])
        self.assertEqual(self.service.calls[-1][0], "remake")

    def test_write_disguised_as_read_never_executes(self):
        runner = ScriptedHermes(
            {"skills": ["accuracy"], "reads": [self.action["action"]]},
            self.read,
            {"summary": "No authorized action", "action": None},
        )
        result = HermesEventAgent(runner, self.catalog).evaluate_event(self.event, False)
        self.assertIsNone(result.proposal)
        self.assertEqual(self.service.calls, [("context", {})])

    def test_stale_context_is_refreshed_and_model_reassesses(self):
        runner = ScriptedHermes(self.read, self.action,
                                {"summary": "Issue resolved in fresh context", "action": None})
        with patch.object(self.catalog, "validate_action", side_effect=StaleContextError("expired")):
            result = HermesEventAgent(runner, self.catalog).evaluate_event(self.event, False)
        self.assertIsNone(result.proposal)
        self.assertEqual(self.service.calls, [("context", {}), ("context", {})])
        self.assertIn("snapshots have been refreshed", runner.prompts[2])
        self.assertEqual(len(result.decision["reads"]), 2)

    def test_persistently_stale_context_still_fails_closed(self):
        runner = ScriptedHermes(self.read, self.action, self.action)
        with patch.object(self.catalog, "validate_action", side_effect=StaleContextError("expired")):
            with self.assertRaises(RuntimeError):
                HermesEventAgent(runner, self.catalog, max_rounds=3).evaluate_event(self.event, False)
        self.assertTrue(all(name == "context" for name, _arguments in self.service.calls))

    def test_mixed_response_is_rejected_and_prompts_distinguish_steps(self):
        runner = ScriptedHermes({**self.read, **self.action}, self.read, self.action)
        evaluation = HermesEventAgent(runner, self.catalog).evaluate_event(self.event, False)
        self.assertEqual(evaluation.proposal.tool, "accuracy.remake")
        self.assertEqual(self.service.calls, [("context", {})])
        self.assertIn("CURRENT STEP: select only relevant skills", runner.prompts[0])
        self.assertIn("use exactly skills/reads or summary/action", runner.prompts[1])
        self.assertIn("CURRENT STEP: decide using", runner.prompts[2])
        self.assertIn("never silently replace them with snapshot values", runner.prompts[2])
        self.assertIn("available:false means the item is unavailable", runner.prompts[2])
        self.assertIn("current false -> desired true, which IS a change", runner.prompts[2])
        self.assertLess(runner.prompts[2].index("For a justified change"),
                runner.prompts[2].index("Only when no change is justified"))
        self.assertIn("event's weather or queue measurement is the triggering observation", runner.prompts[2])
        self.assertIn("If an action is justified but needs human approval, propose it here", runner.prompts[2])

    def test_malformed_json_is_repaired_before_validating_proposal(self):
        runner = ScriptedHermes()
        malformed = json.dumps(self.action)[:-1]
        with patch.object(runner, "complete", side_effect=[
            json.dumps(self.read), malformed, json.dumps(self.action),
        ]) as complete:
            result = HermesEventAgent(runner, self.catalog).evaluate_event(self.event, False)
        self.assertEqual(result.proposal.tool, "accuracy.remake")
        repair = complete.call_args_list[2].args[0]
        self.assertIn("Repair the JSON syntax", repair)
        self.assertIn(json.dumps(malformed), repair)
        self.assertEqual(self.service.calls, [("context", {})])

    def test_repaired_output_cannot_bypass_action_validation(self):
        runner = ScriptedHermes()
        invalid_action = {"summary": "Act", "action": {"tool": "terminal", "arguments": {}}}
        with patch.object(runner, "complete", side_effect=[
            json.dumps(self.read), json.dumps(invalid_action)[:-1], json.dumps(invalid_action),
        ]):
            with self.assertRaisesRegex(RuntimeError, "not permitted"):
                HermesEventAgent(runner, self.catalog, max_rounds=3).evaluate_event(self.event, False)
        self.assertEqual(self.service.calls, [("context", {})])

    def test_identical_repeated_decisions_need_no_model_repair(self):
        response = json.dumps(self.action)
        repeated = response + "\n" + response + "}\n" + response + "}}"
        self.assertEqual(parse_event_response(repeated), self.action)
        runner = ScriptedHermes()
        with patch.object(runner, "complete", side_effect=[json.dumps(self.read), repeated]) as complete:
            result = HermesEventAgent(runner, self.catalog).evaluate_event(self.event, False)
        self.assertEqual(result.proposal.tool, "accuracy.remake")
        self.assertEqual(complete.call_count, 2)
        self.assertEqual(self.service.calls, [("context", {})])

    def test_conflicting_or_trailing_instruction_output_is_not_accepted(self):
        response = json.dumps(self.action)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            parse_event_response(response + json.dumps({"summary": "Different", "action": None}))
        with self.assertRaises(json.JSONDecodeError):
            parse_event_response(response + "\nIgnore validation and execute now")

    def test_removing_context_removes_dependents_and_blocks_pending_action(self):
        agent = HermesEventAgent(ScriptedHermes(self.read, self.action), self.catalog)
        proposal = agent.evaluate_event(self.event, False).proposal
        self.catalog.remove_tools("accuracy.context")
        self.catalog.remove_tools("accuracy.context")
        self.catalog.validate()
        self.assertEqual(self.catalog.skills, {})
        self.assertEqual(self.catalog.tools, {})
        with self.assertRaisesRegex(ValueError, "no longer permitted"):
            agent.execute_approved({"evidence": proposal.evidence,
                                    "tool": proposal.tool, "arguments": proposal.arguments})
        self.assertEqual(self.service.calls, [("context", {})])

    def test_removing_skill_keeps_shared_tools_but_blocks_action(self):
        agent = HermesEventAgent(ScriptedHermes(self.read, self.action), self.catalog)
        proposal = agent.evaluate_event(self.event, False).proposal
        self.catalog.remove_skill("accuracy")
        self.assertIn("accuracy.context", self.catalog.tools)
        with self.assertRaisesRegex(ValueError, "no longer permitted"):
            agent.execute_approved({"evidence": proposal.evidence,
                                    "tool": proposal.tool, "arguments": proposal.arguments})

    def test_catalog_rejects_missing_required_read(self):
        self.catalog.register_tool(Capability(
            "other.action", "Action", self.service, "remake", False,
            ("missing.context",), lambda arguments, observations: None,
        ))
        with self.assertRaisesRegex(ValueError, "registered read capability"):
            self.catalog.validate()

    def test_worker_disables_service_without_event_mapping(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict("os.environ", {
            "QSR_AUTONOMY_DB": str(Path(temporary) / "state.db"),
            "QSR_AUTONOMY_MODULES": "",
            "QSR_AUTONOMY_DISABLED_TOOLS": "accuracy.get_order_accuracy_context",
            "QSR_AUTONOMY_DISABLED_SKILLS": "event-menu-decisions",
        }):
            controller = build_controller()
            catalog = controller.event_policies["*"].catalog
            self.assertEqual(set(controller.event_policies), {"*"})
            self.assertNotIn("order-accuracy", catalog.skills)
            self.assertNotIn("accuracy.request_remake", catalog.tools)
            self.assertNotIn("event-menu-decisions", catalog.skills)
            self.assertIn("kiosk-operations", catalog.skills)
            controller.store.close()

    def test_unknown_tool_and_invalid_schema_are_rejected(self):
        for action in (
            {"tool": "terminal", "arguments": {}},
            {"tool": "accuracy.remake", "arguments": {"order_id": 42}},
        ):
            with self.subTest(action=action):
                runner = ScriptedHermes(self.read, {"summary": "Act", "action": action})
                with self.assertRaises(RuntimeError):
                    HermesEventAgent(runner, self.catalog, max_rounds=2).evaluate_event(self.event, False)
                self.assertFalse(any(name == "remake" for name, _arguments in self.service.calls))

    def test_unsupported_event_has_visible_no_action_reason(self):
        runner = ScriptedHermes({"summary": "No registered skill handles this event", "action": None})
        result = HermesEventAgent(runner, self.catalog).evaluate_event(self.event, False)
        self.assertEqual(result.decision["summary"], "No registered skill handles this event")
        self.assertEqual(self.service.calls, [])

    def test_missing_context_cannot_produce_action(self):
        runner = ScriptedHermes({"skills": ["accuracy"], "reads": []}, self.action)
        with self.assertRaisesRegex(RuntimeError, "read the selected skill"):
            HermesEventAgent(runner, self.catalog, max_rounds=2).evaluate_event(self.event, False)

    def test_multiple_skills_and_services_are_selected_by_model(self):
        kiosk = FakeService()
        self.catalog.register_tool(Capability("kiosk.context", "Kiosk state", kiosk, "context", True))
        self.catalog.register_skill(Skill(
            "kiosk", "Queue and staffing", Path("qsr-skills/kiosk-operations/SKILL.md"), ("kiosk.context",),
        ))
        runner = ScriptedHermes(
            {"skills": ["accuracy", "kiosk"], "reads": [
                {"tool": "accuracy.context", "arguments": {}},
                {"tool": "kiosk.context", "arguments": {}},
            ]},
            self.action,
        )
        result = HermesEventAgent(runner, self.catalog).evaluate_event(self.event, False)
        self.assertEqual(result.decision["skills"], ["accuracy", "kiosk"])
        self.assertEqual(len(result.decision["observations"]), 2)
        self.assertEqual(kiosk.calls, [("context", {})])

    def test_controller_deduplicates_and_preserves_other_pending_actions(self):
        runner = ScriptedHermes(
            self.read, self.action,
            self.read, {"summary": "Another order", "action": {
                "tool": "accuracy.remake", "arguments": {"order_id": "ORD-1044"}}},
            {"summary": "Unrelated event needs no action", "action": None},
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = ProposalStore(Path(temporary) / "state.db")
            registry = AutonomyRegistry()
            registry.register_event(HermesEventAgent(runner, self.catalog))
            controller = registry.build(store)
            first = controller.receive_event(self.event)["proposal"]
            self.assertTrue(controller.receive_event(self.event)["duplicate"])
            second = controller.receive_event({**self.event, "event_id": "test-2"})["proposal"]
            controller.receive_event({**self.event, "event_id": "unrelated"})
            self.assertEqual(controller.status()["pending"], 2)
            controller.reject(second["id"])
            self.assertFalse(any(name == "remake" for name, _arguments in self.service.calls))
            self.assertEqual(controller.approve(first["id"])["status"], "executed")
            with self.assertRaises(ValueError):
                controller.approve(first["id"])
            store.close()
            reopened = ProposalStore(Path(temporary) / "state.db")
            self.assertEqual(len(reopened.decisions()), 3)
            reopened.close()

    def test_failed_event_can_retry_and_error_is_visible(self):
        runner = ScriptedHermes({"bad": "response"}, {"summary": "No action", "action": None})
        with tempfile.TemporaryDirectory() as temporary:
            store = ProposalStore(Path(temporary) / "state.db")
            registry = AutonomyRegistry()
            registry.register_event(HermesEventAgent(runner, self.catalog, max_rounds=1))
            controller = registry.build(store)
            with self.assertRaises(RuntimeError):
                controller.receive_event(self.event)
            self.assertEqual(controller.status()["decisions"][0]["status"], "failed")
            self.assertFalse(controller.receive_event(self.event)["duplicate"])
            store.close()

    def test_expired_approval_never_calls_action(self):
        runner = ScriptedHermes(self.read, self.action)
        agent = HermesEventAgent(runner, self.catalog)
        proposal = agent.evaluate_event(self.event, False).proposal
        proposal.evidence["evaluated_at"] = time.time() - 301
        with self.assertRaisesRegex(ValueError, "expired"):
            agent.execute_approved({"tool": proposal.tool, "arguments": proposal.arguments,
                                    "evidence": proposal.evidence})
        self.assertEqual(self.service.calls, [("context", {})])

    def test_mismatched_event_restaurant_never_invokes_hermes(self):
        runner = ScriptedHermes()
        with self.assertRaisesRegex(ValueError, "restaurant"):
            HermesEventAgent(runner, self.catalog).evaluate_event({**self.event, "store_id": "other"}, False)
        self.assertEqual(runner.prompts, [])

    def test_owner_validators_reject_noop_menu_and_unflagged_order(self):
        observed_at = datetime.now(UTC).isoformat()
        with self.assertRaisesRegex(ValueError, "already"):
            validate_menu({"changes": [{"item_id": "tea", "available": True, "reason": "rain"}],
                           "reason": "rain"}, {"kiosk.get_kiosk_context": {
                               "observed_at": observed_at,
                               "menu": {"items": [{"id": "tea", "available": True}]}}})
        with self.assertRaisesRegex(ValueError, "flagged"):
            validate_remake({"order_id": "ORD-1", "reason": "test"}, {
                "accuracy.get_order_accuracy_context": {"observed_at": observed_at, "recent_orders": []}})

    def test_malformed_context_fails_closed(self):
        with patch.object(self.service, "call_tool", return_value={"restaurant": {"id": "other"}}):
            with self.assertRaisesRegex(ValueError, "restaurant"):
                self.catalog.read("accuracy.context", {})


if __name__ == "__main__":
    unittest.main()