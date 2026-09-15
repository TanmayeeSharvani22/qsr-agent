#!/usr/bin/env python3

from __future__ import annotations

import os
import unittest
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