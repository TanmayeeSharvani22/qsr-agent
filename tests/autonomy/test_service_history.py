from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from autonomy.learning import (Journal, describe_rules, event_fields, event_service,
                               induce_missing_rules, matching_settings, new_record, render_skill, validate_record,
                               verify_rules)
from autonomy.learning_runner import counts_by_service

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "learning/simulated/event_op_response.jsonl"
KIOSK_DATASET = ROOT / "learning/simulated/kiosk-queue-history.jsonl"
DATASET = COMMON
START = datetime(2026, 9, 1, tzinfo=UTC)
TOOLS = [{"name": "kiosk.change_menu_items", "read_only": False,
          "inputSchema": {"properties": {"changes": {}, "reason": {}}}},
         {"name": "accuracy.request_remake", "read_only": False,
          "inputSchema": {"properties": {"order_id": {}, "reason": {}}}}]


def _simulator():
    spec = importlib.util.spec_from_file_location("simulate_service_history",
                                                  ROOT / "scripts/simulate_service_history.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class ServiceHistoryTests(unittest.TestCase):
    def test_committed_dataset_is_synthetic_valid_jsonl_and_matches_generator(self):
        records = _load(DATASET)
        for record in records:
            validate_record(record)
            self.assertEqual(record["source"], "simulated")
            self.assertTrue(record["id"].startswith("sim-"))
        simulator = _simulator()
        self.assertEqual(records, json.loads(json.dumps(simulator.simulate_all(8, 7, START))))
        self.assertEqual(len({r["id"] for r in records}), len(records))
        self.assertEqual({r["event"]["service"] for r in records}, {"kiosk", "weather", "accuracy"})

    def test_common_file_keeps_kiosk_history_and_imports_idempotently(self):
        common = _load(COMMON)
        kiosk = [r for r in common if r["event"]["service"] == "kiosk"]
        self.assertEqual(kiosk, _load(KIOSK_DATASET))  # backwards compatible with the original kiosk file
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory))
            self.assertEqual(journal.append(common), len(common))
            self.assertEqual(journal.append(common), 0)
            self.assertEqual(journal.append(_load(KIOSK_DATASET)), 0)  # old kiosk file adds no duplicates
            counts = counts_by_service(journal.records())
        self.assertEqual(set(counts), {"kiosk", "weather", "accuracy"})
        for service in counts:  # each service clears the UI's default threshold of 20
            self.assertGreaterEqual(sum(counts[service].values()), 20)

    def test_dataset_covers_success_failure_silence_and_unregistered_action_cases(self):
        by_service: dict[str, Counter] = {}
        for record in _load(DATASET):
            by_service.setdefault(record["event"]["service"], Counter())[record["operator"]["kind"]] += 1
        for service in ("weather", "accuracy"):
            self.assertTrue({"instruction", "none", "rejected", "approved"} <= set(by_service[service]), service)
        accuracy = [r for r in _load(DATASET) if r["event"]["service"] == "accuracy"]
        self.assertTrue(any(r["operator"]["kind"] == "instruction" and not r["operator"]["tool_calls"]
                            for r in accuracy))  # comp: typed, no registered tool

    def test_weather_rules_are_supported_and_remake_cannot_be_generalised(self):
        records = _load(DATASET)
        weather = [r for r in records if r["event"]["service"] == "weather"]
        accuracy = [r for r in records if r["event"]["service"] == "accuracy"]
        cold_off = next(c["arguments"]["changes"] for r in weather for c in r["operator"]["tool_calls"]
                        if c["arguments"]["changes"][0] == {"item_id": "DRINK-004", "available": False,
                                                            "reason": "cold or wet weather"}
                        and len(c["arguments"]["changes"]) == 2)
        rain = {"event": "weather_changed", "propose": {"tool": "kiosk.change_menu_items", "set": {"changes": cold_off}},
                "when": [{"field": "event.is_raining", "op": "==", "value": True},
                         {"field": "event.previous.is_raining", "op": "==", "value": False}]}
        accepted, dropped = verify_rules([rain], weather, TOOLS)
        self.assertEqual((len(accepted), dropped), (1, []))
        self.assertGreaterEqual(accepted[0]["support"], 5)
        remake = {"event": "order_mismatch_detected", "propose": {"tool": "accuracy.request_remake",
                                                         "set": {"order_id": "SIM-1001"}},
                  "when": [{"field": "event.venue", "op": "==", "value": "take-away"}]}
        self.assertEqual(verify_rules([remake], accuracy, TOOLS)[0], [])

    def test_menu_state_and_event_bound_arguments_make_weather_and_accuracy_learnable(self):
        records = _load(DATASET)
        weather = [r for r in records if r["event"]["service"] == "weather"]
        accuracy = [r for r in records if r["event"]["service"] == "accuracy"]
        # Menu list items are addressable by their real kiosk id, so "only if not already off" can be expressed.
        fields = event_fields(weather[0]["event"]["payload"], weather[0]["context"])
        self.assertIn("context[kiosk.get_kiosk_context].menu.items.DRINK-004.available", fields)
        induced = induce_missing_rules([], weather)
        accepted, _dropped = verify_rules(induced, weather, TOOLS)
        self.assertTrue(any("DRINK-004" in json.dumps(rule["propose"]) and rule["support"] >= 5
                            for rule in accepted))
        # The remake copies the order id from the event; only take-away orders with missing items are remade.
        remake = {"event": "order_mismatch_detected", "propose": {"tool": "accuracy.request_remake",
                                                         "set": {"order_id": {"from": "event.order_id"}}},
                  "when": [{"field": "event.venue", "op": "==", "value": "take-away"},
                           {"field": "event.missing_items.count", "op": ">=", "value": 1}]}
        accepted, dropped = verify_rules([remake], accuracy, TOOLS)
        self.assertEqual(len(accepted), 1, dropped)
        self.assertEqual(accepted[0]["rejected"], 0)
        # A rule copied from a learned skill's JSON block has no `event`; one event type makes it unambiguous.
        without_event = {key: value for key, value in remake.items() if key != "event"}
        self.assertEqual(verify_rules([without_event], accuracy, TOOLS)[0][0]["event"], "order_mismatch_detected")
        live = event_fields({"order_id": "TA-4242", "venue": "take-away", "reason": "missing:1",
                             "missing_items": [{"name": "french fries", "quantity": 1}], "extra_items": []}, {})
        self.assertEqual(matching_settings(accepted, live), {"accuracy.request_remake": {"order_id": "TA-4242"}})
        self.assertEqual(matching_settings(accepted, {**live, "event.venue": "dine-in"}), {})
        self.assertEqual(matching_settings(accepted, {"event.venue": "take-away",
                                                      "event.missing_items.count": 1}), {})  # nothing to bind
        described = describe_rules(render_skill("accuracy", accepted, TOOLS))
        self.assertEqual(described[0]["then"], "order_id → the event's order_id")
        cold_on = [rule for rule in verify_rules(induce_missing_rules([], weather), weather, TOOLS)[0]
                   if '"available": true' in json.dumps(rule["propose"])]
        self.assertIn("DRINK-004 on", " ".join(rule["then"] for rule in describe_rules(
            render_skill("weather", cold_on, TOOLS))))

    def test_induction_learns_a_label_rule_and_a_smaller_second_pattern(self):
        # Live-test policy: dine-in remade; take-away remade only with 2 missing items, else rejected.
        records = []
        for index, (venue, missing, kind) in enumerate(
                [("dine-in", 1, "approved")] * 6 + [("take-away", 2, "approved")] * 3
                + [("take-away", 1, "rejected")] * 5):
            order_id = f"O-{index}"
            payload = {"order_id": order_id, "venue": venue, "reason": f"missing:{missing}",
                       "missing_items": [{"name": "item"}] * missing, "extra_items": [],
                       **({"accuracy_score": 0.62, "quantity_mismatches": []} if venue == "dine-in"
                          else {"quantity_mismatch": []})}
            proposed = {"tool": "accuracy.request_remake", "arguments": {"order_id": order_id, "reason": "x"},
                        "status": "executed" if kind == "approved" else "rejected"}
            records.append(new_record(source="live", kind=kind, proposed=proposed, event={
                "event_id": f"e{index}", "type": "order_mismatch_detected", "service": "accuracy",
                "payload": payload}))
        accepted, dropped = verify_rules(induce_missing_rules([], records), records, TOOLS)
        self.assertEqual(len(accepted), 2, dropped)
        self.assertIn([{"field": "event.venue", "op": "==", "value": "dine-in"}], [rule["when"] for rule in accepted])
        self.assertEqual(sorted((rule["support"], rule["matched"], rule["rejected"]) for rule in accepted),
                         [(3, 3, 0), (6, 6, 0)])

    def test_weather_envelope_service_and_malformed_or_sparse_records(self):
        self.assertEqual(event_service({"event_type": "weather_changed", "service": "weather", "data": {}}), "weather")
        # Producers that omit `service` are resolved from the event type; unregistered types stay unknown.
        self.assertEqual(event_service({"event_type": "weather_changed", "data": {}}), "weather")
        self.assertEqual(event_service({"event_type": "order_mismatch", "data": {}}), "accuracy")
        self.assertEqual(event_service({"event_type": "table_dirty", "data": {}}), "unknown")
        with patch.dict("os.environ", {"QSR_EVENT_SERVICES": "table_dirty=table, bad=Bad Name"}):
            self.assertEqual(event_service({"event_type": "table_dirty", "data": {}}), "table")
            self.assertEqual(event_service({"event_type": "bad", "data": {}}), "unknown")
        event = {"event_id": "e1", "type": "order_mismatch_detected", "service": "accuracy", "payload": {}}
        sparse = new_record(source="simulated", event=event, kind="none")  # no context, text or tool calls
        self.assertEqual(sparse["context"], {})
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory))
            for bad in ({**sparse, "id": "x", "source": "production"},
                        {**sparse, "id": "y", "event": {**event, "service": "Bad Service"}},
                        {**sparse, "id": "z", "operator": {"kind": "instruction", "text": "", "tool_calls": []}}):
                with self.assertRaises(ValueError):
                    journal.append([bad])
            self.assertEqual(journal.records(), [])


if __name__ == "__main__":
    unittest.main()
