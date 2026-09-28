from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from autonomy.advisor import MenuChange, MenuDecision, parse_menu_decision
from autonomy.event_menu_policy import HermesEventMenuPolicy
from autonomy.models import ProposedAction
from autonomy.registry import AutonomyRegistry, load_extensions
from autonomy.store import ProposalStore


class FakeKioskClient:
    def __init__(self) -> None:
        self.availability = {
            "burger-classic": True,
            "chicken-wrap": True,
            "fries": True,
            "shake": True,
            "hot-chocolate": False,
            "tea": False,
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        arguments = arguments or {}
        self.calls.append((name, arguments))
        if name == "get_kiosk_context":
            return {
                "operations": {
                    "queue_count": 7,
                    "estimated_wait_minutes": 6,
                    "staff_on_duty": 8,
                },
                "weather": {
                    "condition": "clear",
                    "is_raining": False,
                    "temperature_c": 18.0,
                },
                "recent_activity": {
                    "orders_last_15_minutes": 18,
                    "abandoned_sessions": 2,
                },
                "menu": {
                    "items": [
                        {"id": item_id, "available": available}
                        for item_id, available in self.availability.items()
                    ]
                },
                "observed_at": "2026-09-21T12:00:00Z",
            }
        if name == "change_menu_items":
            for change in arguments["changes"]:
                self.availability[change["item_id"]] = change["available"]
            return {
                "executed": True,
                "status": "accepted",
                "action_id": "test-menu-bundle",
            }
        raise AssertionError(f"unexpected tool: {name}")


class FakeMenuAdvisor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.error: Exception | None = None
        self.decisions = {
            "weather_changed": MenuDecision(
                summary="Rain favors warm drinks",
                confidence=0.92,
                changes=(
                    MenuChange("hot-chocolate", True, "Warm option for rainy weather"),
                    MenuChange("tea", True, "Alternative warm drink"),
                ),
                raw_response='{"summary":"Rain favors warm drinks"}',
            ),
            "queue_count_changed": MenuDecision(
                summary="Reduce preparation pressure during the queue spike",
                confidence=0.87,
                changes=(
                    MenuChange("shake", False, "Temporarily remove a slower item"),
                ),
                raw_response='{"summary":"Reduce preparation pressure"}',
            ),
        }

    def decide(
        self,
        event_type: str,
        event_data: dict[str, Any],
        context: dict[str, Any],
    ) -> MenuDecision:
        self.calls.append((event_type, event_data, context))
        if self.error:
            raise self.error
        return self.decisions[event_type]


class HermesEventMenuAutonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = ProposalStore(Path(self.temporary_directory.name) / "state.db")
        self.client = FakeKioskClient()
        self.advisor = FakeMenuAdvisor()
        registry = AutonomyRegistry()
        registry.register_service(
            self.client, "get_kiosk_context", "change_menu_items"
        )
        registry.register_event(
            HermesEventMenuPolicy(
                advisor=self.advisor,
                policy_id="hermes-weather-menu",
                event_type="weather_changed",
            )
        )
        registry.register_event(
            HermesEventMenuPolicy(
                advisor=self.advisor,
                policy_id="hermes-queue-menu",
                event_type="queue_count_changed",
            )
        )
        self.controller = registry.build(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()

    @staticmethod
    def weather_event(event_id: str = "weather-1") -> dict[str, Any]:
        return {
            "event_id": event_id,
            "event_type": "weather_changed",
            "occurred_at": "2026-09-21T12:00:00Z",
            "data": {
                "condition": "rain",
                "is_raining": True,
                "temperature_c": 14.0,
                "source": "weather-service",
            },
        }

    @staticmethod
    def queue_event(event_id: str = "queue-1") -> dict[str, Any]:
        return {
            "event_id": event_id,
            "event_type": "queue_count_changed",
            "occurred_at": "2026-09-21T12:01:00Z",
            "data": {"queue_count": 12},
        }

    def test_weather_event_uses_hermes_and_waits_for_approval(self) -> None:
        result = self.controller.receive_event(self.weather_event())

        proposal = result["proposal"]
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(proposal["trigger_type"], "hermes")
        self.assertEqual(proposal["tool"], "change_menu_items")
        self.assertEqual(
            [change["item_id"] for change in proposal["arguments"]["changes"]],
            ["hot-chocolate", "tea"],
        )
        self.assertEqual(proposal["evidence"]["decision_source"], "hermes")
        self.assertFalse(self.client.availability["hot-chocolate"])
        self.assertEqual(self.advisor.calls[0][0], "weather_changed")
        self.assertTrue(self.advisor.calls[0][2]["weather"]["is_raining"])
        self.assertEqual(self.advisor.calls[0][2]["weather"]["temperature_c"], 14.0)

        approved = self.controller.approve(proposal["id"])

        self.assertEqual(approved["status"], "executed")
        self.assertTrue(self.client.availability["hot-chocolate"])
        self.assertTrue(self.client.availability["tea"])

    def test_queue_event_uses_hermes_and_waits_for_approval(self) -> None:
        proposal = self.controller.receive_event(self.queue_event())["proposal"]

        self.assertEqual(proposal["arguments"]["changes"][0]["item_id"], "shake")
        self.assertTrue(self.client.availability["shake"])
        self.assertEqual(self.advisor.calls[0][0], "queue_count_changed")
        self.assertEqual(self.advisor.calls[0][2]["operations"]["queue_count"], 12)

        self.controller.approve(proposal["id"])
        self.assertFalse(self.client.availability["shake"])

    def test_rejection_never_calls_menu_action(self) -> None:
        proposal = self.controller.receive_event(self.weather_event())["proposal"]

        rejected = self.controller.reject(proposal["id"])

        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(
            [name for name, _arguments in self.client.calls], ["get_kiosk_context"]
        )

    def test_duplicate_event_does_not_call_context_or_hermes_twice(self) -> None:
        event = self.weather_event("weather-duplicate")
        self.controller.receive_event(event)

        duplicate = self.controller.receive_event(event)

        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(len(self.advisor.calls), 1)
        self.assertEqual(
            [name for name, _arguments in self.client.calls], ["get_kiosk_context"]
        )

    def test_repeated_recommendation_reuses_pending_proposal(self) -> None:
        first = self.controller.receive_event(self.weather_event("weather-1"))["proposal"]
        second = self.controller.receive_event(self.weather_event("weather-2"))["proposal"]

        self.assertEqual(first["id"], second["id"])
        pending = [item for item in self.store.list() if item["status"] == "pending"]
        self.assertEqual(len(pending), 1)

    def test_current_state_removes_no_op_recommendations(self) -> None:
        self.client.availability["hot-chocolate"] = True
        self.client.availability["tea"] = True

        result = self.controller.receive_event(self.weather_event())

        self.assertIsNone(result["proposal"])

    def test_empty_hermes_changes_creates_no_proposal(self) -> None:
        self.advisor.decisions["queue_count_changed"] = MenuDecision(
            summary="Current menu already fits demand",
            confidence=0.75,
            changes=(),
            raw_response='{"changes":[]}',
        )

        result = self.controller.receive_event(self.queue_event())

        self.assertIsNone(result["proposal"])

    def test_failed_advisor_event_can_be_retried(self) -> None:
        event = self.queue_event("queue-retry")
        self.advisor.error = ValueError("invalid advisor response")
        with self.assertRaisesRegex(ValueError, "invalid advisor response"):
            self.controller.receive_event(event)
        self.advisor.error = None

        result = self.controller.receive_event(event)

        self.assertFalse(result["duplicate"])
        self.assertIsNotNone(result["proposal"])

    def test_invalid_event_can_be_retried_with_same_id(self) -> None:
        event = self.queue_event("queue-invalid")
        event["data"]["queue_count"] = -1
        with self.assertRaisesRegex(ValueError, "queue_count"):
            self.controller.receive_event(event)
        event["data"]["queue_count"] = 8

        result = self.controller.receive_event(event)

        self.assertFalse(result["duplicate"])

    def test_parser_rejects_unknown_or_unbounded_changes(self) -> None:
        valid = parse_menu_decision(
            '{"summary":"Add warm drinks","confidence":0.9,"changes":'
            '[{"item_id":"tea","available":true,"reason":"Rain"}]}',
            {"tea", "hot-chocolate"},
        )
        self.assertEqual(valid.changes[0].item_id, "tea")
        with self.assertRaisesRegex(ValueError, "unknown menu item"):
            parse_menu_decision(
                '{"summary":"Invent item","confidence":1,"changes":'
                '[{"item_id":"soup","available":true,"reason":"Rain"}]}',
                {"tea"},
            )

    def test_registry_requires_context_tool(self) -> None:
        registry = AutonomyRegistry()
        with self.assertRaisesRegex(ValueError, "context tool is not registered"):
            registry.register_event(
                HermesEventMenuPolicy(
                    advisor=self.advisor,
                    policy_id="owner-weather-menu",
                    event_type="weather_changed",
                )
            )

    def test_removed_policy_pending_proposal_is_superseded_and_hidden(self) -> None:
        legacy = self.store.create(
            ProposedAction(
                policy_id="legacy-polling-policy",
                trigger_type="poll",
                summary="Legacy action",
                evidence={},
                tool="change_menu",
                arguments={"item_id": "shake", "available": False},
            )
        )

        registry = AutonomyRegistry()
        registry.register_service(
            self.client, "get_kiosk_context", "change_menu_items"
        )
        registry.register_event(
            HermesEventMenuPolicy(
                advisor=self.advisor,
                policy_id="hermes-weather-menu",
                event_type="weather_changed",
            )
        )
        controller = registry.build(self.store)

        self.assertEqual(self.store.get(legacy["id"])["status"], "superseded")
        self.assertEqual(controller.status()["proposals"], [])

    def test_extension_module_registers_with_registry(self) -> None:
        registry = AutonomyRegistry()
        received: list[AutonomyRegistry] = []
        module = SimpleNamespace(register_autonomy=received.append)
        with patch("autonomy.registry.importlib.import_module", return_value=module) as load:
            load_extensions(registry, ["owner.menu_autonomy", ""])

        load.assert_called_once_with("owner.menu_autonomy")
        self.assertEqual(received, [registry])


if __name__ == "__main__":
    unittest.main()