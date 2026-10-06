#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastmcp import Client, FastMCP

import kiosk_server
import order_accuracy_server
from service_base import GateLevel, QsrService

HERE = Path(__file__).resolve().parent


def _call(service: QsrService, name: str, arguments: dict | None = None):
    async def call():
        async with Client(service.build()) as client:
            return await client.call_tool(name, arguments or {}, raise_on_error=False)

    return asyncio.run(call())


def _tools(service: QsrService) -> dict:
    async def tools():
        async with Client(service.build()) as client:
            return {tool.name: tool for tool in await client.list_tools()}

    return asyncio.run(tools())


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
        self.assertEqual(result["gate"], "needs_approval")


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.log_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MCP_LOG_DIR": self.log_dir.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.log_dir.cleanup()

    def test_tools_expose_exact_schemas_and_gates(self) -> None:
        for module in (kiosk_server, order_accuracy_server):
            with self.subTest(service=module.svc.name):
                tools = _tools(module.svc)
                self.assertEqual(set(tools), {*module.TOOL_SCHEMAS, "describe"})
                for name, schema in module.TOOL_SCHEMAS.items():
                    self.assertEqual(tools[name].input_schema, schema)
                for name in module.svc.act_tools:
                    level = module.svc.policy.level(name).value
                    self.assertTrue(tools[name].description.startswith(f"[gate={level}]"))

    def test_read_tool_returns_structured_content(self) -> None:
        result = _call(order_accuracy_server.svc, "get_order_accuracy_context")
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["restaurant"]["id"], "qsr-001")

    def test_describe_reports_contract(self) -> None:
        contract = _call(order_accuracy_server.svc, "describe").structured_content
        self.assertEqual(contract["act_tools"]["issue_comp"]["gate"], "needs_approval")
        self.assertEqual(contract["act_tools"]["request_remake"]["gate"], "automatic")
        self.assertIn("order_mismatch", contract["event_types"])

    def test_action_goes_through_gate_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"QSR_KIOSK_STATE": str(Path(directory) / "state.json")}
        ):
            result = _call(kiosk_server.svc, "change_menu_items", {
                "changes": [{"item_id": "tea", "available": True, "reason": "Rain"}],
                "reason": "Test",
            })
        self.assertEqual((result.structured_content["executed"], result.structured_content["gate"]),
                         (True, "automatic"))
        events = [json.loads(line)["event"] for line in
                  (Path(self.log_dir.name) / "kiosk-placeholder.jsonl").read_text().splitlines()]
        self.assertEqual(events, ["tool_called", "tool_succeeded"])

    def test_denied_and_invalid_actions(self) -> None:
        denied = _call(order_accuracy_server.svc, "issue_comp", {"order_id": "ORD-1042", "amount": 5.0})
        self.assertFalse(denied.is_error)
        self.assertEqual(denied.structured_content["reason"], "awaiting human approval")
        invalid = _call(kiosk_server.svc, "change_menu_items", {"changes": [], "reason": "x"})
        self.assertTrue(invalid.is_error)
        self.assertIn("between one and three", invalid.content[0].text)

    def test_rate_limit_and_unknown_action_are_denied(self) -> None:
        service = QsrService("test", "qsr-001")

        @service.act_tool("act", level=GateLevel.AUTOMATIC, description="d", max_calls=1)
        def act() -> dict:
            return {"done": True}

        self.assertTrue(service.call_action("act")["executed"])
        self.assertEqual(service.call_action("act")["reason"], "rate limit exceeded")
        self.assertEqual(service.policy.evaluate("missing", {}).reason, "not on allow-list")
        with self.assertRaisesRegex(ValueError, "unknown tool"):
            service.set_schemas({"missing": {}})


class TransportTests(unittest.TestCase):
    def test_stdio_is_default(self) -> None:
        with patch.dict(os.environ, {"QSR_MCP_TRANSPORT": "stdio", "MCP_LOG_DIR": tempfile.gettempdir()}), \
                patch.object(FastMCP, "run") as run:
            kiosk_server.svc.run()
        run.assert_called_once_with("stdio", show_banner=False)

    def test_network_transport_uses_configured_binding(self) -> None:
        environment = {
            "QSR_MCP_TRANSPORT": "streamable-http",
            "QSR_MCP_HOST": "0.0.0.0",
            "QSR_MCP_PORT": "8123",
            "MCP_LOG_DIR": tempfile.gettempdir(),
        }
        with patch.dict(os.environ, environment), patch.object(FastMCP, "run") as run:
            kiosk_server.svc.run()
        run.assert_called_once_with("http", show_banner=False, host="0.0.0.0", port=8123)

    def test_invalid_transport_is_rejected(self) -> None:
        with patch.dict(os.environ, {"QSR_MCP_TRANSPORT": "carrier-pigeon", "MCP_LOG_DIR": tempfile.gettempdir()}):
            with self.assertRaisesRegex(ValueError, "QSR_MCP_TRANSPORT"):
                kiosk_server.svc.run()

    def test_stdio_process_round_trip(self) -> None:
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "get_kiosk_context", "arguments": {}}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen(
                [sys.executable, str(HERE / "kiosk_server.py")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                env={**os.environ, "MCP_LOG_DIR": directory},
            )
            try:
                process.stdin.write("".join(json.dumps(request) + "\n" for request in requests))
                process.stdin.flush()
                response = next(message for message in map(json.loads, process.stdout)
                                if message.get("id") == 2)
            finally:
                process.stdin.close()
                process.wait(timeout=10)
                process.stdout.close()
        self.assertEqual(response["result"]["structuredContent"]["restaurant"]["id"], "qsr-001")


if __name__ == "__main__":
    unittest.main()