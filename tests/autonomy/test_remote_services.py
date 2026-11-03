from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from autonomy.mcp import HttpMcpClient
from autonomy.service_capabilities import MergedAccuracyClient, validate_remake
from autonomy.worker import build_registry

ROOT = Path(__file__).resolve().parents[2]


def _context(venue: str, orders: list[dict], observed_at: datetime) -> dict:
    return {"restaurant": {"id": "qsr-001"}, "observed_at": observed_at.isoformat(),
            "summary": {"orders_observed": len(orders), "orders_flagged": sum(o["result"] == "flagged" for o in orders),
                        "orders_accurate": sum(o["result"] == "accurate" for o in orders)},
            "stations": [{"id": f"{venue}-1", "type": venue}], "recent_orders": orders}


class FakeAccuracy:
    def __init__(self, context: dict | None):
        self.context, self.calls = context, []

    def list_tools(self):
        return [{"name": "get_order_accuracy_context"}, {"name": "request_remake"}]

    def call_tool(self, name, arguments=None):
        if self.context is None:
            raise OSError("connection refused")
        if name == "get_order_accuracy_context":
            return self.context
        self.calls.append((name, arguments))
        return {"executed": True}


class RemoteServicesTests(unittest.TestCase):
    def test_take_away_and_dine_in_merge_into_one_accuracy_service(self):
        now = datetime.now(UTC)
        take_away = FakeAccuracy(_context("take_away", [
            {"order_id": "539", "result": "flagged", "issues": [{"type": "missing_item", "name": "apple"}]}],
            now - timedelta(seconds=5)))
        dine_in = FakeAccuracy(_context("dine_in", [
            {"order_id": "MCD-1", "result": "accurate", "issues": []},
            {"order_id": "MCD-2", "result": "flagged", "issues": [{"type": "extra_item", "name": "cola"}]}], now))
        client = MergedAccuracyClient([take_away, dine_in])
        context = client.call_tool("get_order_accuracy_context")
        self.assertEqual([o["order_id"] for o in context["recent_orders"]], ["539", "MCD-1", "MCD-2"])
        self.assertEqual(context["summary"]["orders_flagged"], 2)
        self.assertEqual(context["summary"]["accuracy_rate"], 0.333)
        self.assertEqual(context["observed_at"], (now - timedelta(seconds=5)).isoformat())  # oldest wins
        validate_remake({"order_id": "MCD-2", "reason": "extra cola"},
                        {"accuracy.get_order_accuracy_context": context})
        self.assertEqual(client.call_tool("request_remake", {"order_id": "MCD-2", "reason": "x"}), {"executed": True})
        self.assertEqual((take_away.calls, dine_in.calls), ([], [("request_remake", {"order_id": "MCD-2", "reason": "x"})]))
        with self.assertRaises(ValueError):  # accurate orders are never remade
            client.call_tool("request_remake", {"order_id": "MCD-1", "reason": "x"})
        # One venue offline: the other still answers.
        offline = MergedAccuracyClient([FakeAccuracy(None), dine_in])
        self.assertEqual(len(offline.call_tool("get_order_accuracy_context")["recent_orders"]), 2)
        with self.assertRaises(OSError):
            MergedAccuracyClient([FakeAccuracy(None)]).call_tool("get_order_accuracy_context")

    def test_remote_urls_replace_local_kiosk_and_accuracy_simulations(self):
        remote = {"QSR_KIOSK_MCP_URL": "http://kiosk-host:8014/mcp",
                  "QSR_ORDER_ACCURACY_TAKE_AWAY_MCP_URL": "http://oa-host:8010/mcp",
                  "QSR_ORDER_ACCURACY_DINE_IN_MCP_URL": "", "HERMES_CONFIG": "/nonexistent",
                  "QSR_AUTONOMY_MODULES": "", "QSR_LEARNING_DIR": "/nonexistent"}
        with patch.dict("os.environ", remote):
            catalog = build_registry(ROOT).catalog
        self.assertIsInstance(catalog.tools["kiosk.change_menu_items"].client, HttpMcpClient)
        self.assertIsInstance(catalog.tools["accuracy.request_remake"].client, HttpMcpClient)
        with patch.dict("os.environ", {**remote, "QSR_ORDER_ACCURACY_DINE_IN_MCP_URL": "http://oa-host:8011/mcp"}):
            catalog = build_registry(ROOT).catalog
        self.assertIsInstance(catalog.tools["accuracy.request_remake"].client, MergedAccuracyClient)


if __name__ == "__main__":
    unittest.main()
