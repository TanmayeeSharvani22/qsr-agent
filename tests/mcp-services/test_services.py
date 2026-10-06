#!/usr/bin/env python3

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kiosk_server
import order_accuracy_server
import service_runtime


class DomainContractTests(unittest.TestCase):
    def test_kiosk_context_has_decision_fields(self) -> None:
        context = kiosk_server.get_kiosk_context()

        self.assertEqual(context["schema_version"], "1.0")
        self.assertIn("queue_count", context["operations"])
        self.assertIn("estimated_wait_minutes", context["operations"])
        self.assertIn("items", context["menu"])
        self.assertIn("observed_at", context)

    def test_kiosk_context_does_not_own_weather(self) -> None:
        self.assertNotIn("weather", kiosk_server.get_kiosk_context())

    def test_kiosk_queue_scenario_can_be_configured(self) -> None:
        with patch.dict(os.environ, {"QSR_QUEUE_COUNT": "0", "QSR_ESTIMATED_WAIT_MINUTES": "0"}):
            context = kiosk_server.get_kiosk_context()
        self.assertEqual(context["operations"]["queue_count"], 0)
        self.assertEqual(context["operations"]["estimated_wait_minutes"], 0)
        for variable in ("QSR_QUEUE_COUNT", "QSR_ESTIMATED_WAIT_MINUTES"):
            for value in ("-1", "not-a-number"):
                with self.subTest(variable=variable, value=value), patch.dict(os.environ, {variable: value}):
                    with self.assertRaises(ValueError):
                        kiosk_server.get_kiosk_context()

    def test_menu_change_is_visible_in_later_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "kiosk-state.json"
            with patch.dict(os.environ, {"QSR_KIOSK_STATE": str(state_path)}):
                result = kiosk_server.change_menu(
                    item_id="hot-chocolate",
                    available=True,
                    reason="Rain policy approved",
                )
                context = kiosk_server.get_kiosk_context()

        hot_chocolate = next(
            item for item in context["menu"]["items"] if item["id"] == "hot-chocolate"
        )
        self.assertEqual(result["status"], "accepted")
        self.assertTrue(hot_chocolate["available"])
        self.assertEqual(hot_chocolate["availability_reason"], "Rain policy approved")

    def test_menu_change_normalizes_common_item_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "kiosk-state.json"
            with patch.dict(os.environ, {"QSR_KIOSK_STATE": str(state_path)}):
                result = kiosk_server.change_menu(
                    item_id="hot_chocolate",
                    available=False,
                    reason="Operator request",
                )

        self.assertEqual(result["requested_change"]["item_id"], "hot-chocolate")

    def test_menu_bundle_persists_bounded_changes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            state_path = Path(temporary_directory) / "kiosk-state.json"
            with patch.dict(os.environ, {"QSR_KIOSK_STATE": str(state_path)}):
                result = kiosk_server.change_menu_items(
                    changes=[
                        {
                            "item_id": "hot-chocolate",
                            "available": True,
                            "reason": "Warm drink for rain",
                        },
                        {
                            "item_id": "tea",
                            "available": True,
                            "reason": "Alternative warm drink",
                        },
                    ],
                    reason="Hermes weather recommendation",
                )
                context = kiosk_server.get_kiosk_context()

        items = {item["id"]: item for item in context["menu"]["items"]}
        self.assertEqual(len(result["changes"]), 2)
        self.assertTrue(items["hot-chocolate"]["available"])
        self.assertTrue(items["tea"]["available"])
        self.assertEqual(items["tea"]["availability_reason"], "Alternative warm drink")

    def test_order_accuracy_context_has_decision_fields(self) -> None:
        context = order_accuracy_server.get_order_accuracy_context()

        self.assertEqual(context["schema_version"], "1.0")
        self.assertIn("accuracy_rate", context["summary"])
        self.assertIn("stations", context)
        self.assertIn("recent_orders", context)
        self.assertIn("observed_at", context)

    def test_comp_is_denied_without_approver(self) -> None:
        result = order_accuracy_server.svc.call_action(
            "issue_comp", order_id="ORD-1042", amount=5.0
        )

        self.assertFalse(result["executed"])
        self.assertEqual(result["level"], "needs_approval")


class TransportTests(unittest.TestCase):
    def test_stdio_uses_dependency_free_bridge(self) -> None:
        with patch.dict(os.environ, {"QSR_MCP_TRANSPORT": "stdio"}, clear=False):
            with patch.object(service_runtime, "serve") as serve:
                service_runtime.run_service(
                    kiosk_server.svc,
                    "kiosk-placeholder",
                    kiosk_server.TOOL_SCHEMAS,
                )

        serve.assert_called_once_with(
            kiosk_server.svc,
            "kiosk-placeholder",
            kiosk_server.TOOL_SCHEMAS,
        )

    def test_network_transport_uses_configured_binding(self) -> None:
        environment = {
            "QSR_MCP_TRANSPORT": "streamable-http",
            "QSR_MCP_HOST": "0.0.0.0",
            "QSR_MCP_PORT": "8123",
        }
        with patch.dict(os.environ, environment, clear=False):
            with patch.object(kiosk_server.svc, "run") as run:
                service_runtime.run_service(
                    kiosk_server.svc,
                    "kiosk-placeholder",
                    kiosk_server.TOOL_SCHEMAS,
                )

        run.assert_called_once_with(
            transport="streamable-http",
            host="0.0.0.0",
            port=8123,
        )


if __name__ == "__main__":
    unittest.main()