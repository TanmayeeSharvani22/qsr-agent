from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autonomy import discovery
from autonomy.event_agent import CapabilityCatalog
from autonomy.learning import (induce_missing_rules, matching_settings, render_skill, service_record,
                               verify_rules)
from autonomy.learning_runner import catalog_tools
from autonomy.mcp import _structured
from autonomy.service_capabilities import register_learned_skills

TABLE_TOOLS = [
    {"name": "get_tables", "description": "Tables and their state.", "inputSchema": {"type": "object"}},
    {"name": "get_table", "inputSchema": {"type": "object", "required": ["table_id"],
                                          "properties": {"table_id": {"type": "string"}}}},
    {"name": "mark_table_cleared", "description": "Mark a table cleared.",
     "inputSchema": {"type": "object", "required": ["table_id"], "additionalProperties": False,
                     "properties": {"table_id": {"type": "string"}}}},
    {"name": "seat_party", "annotations": {"readOnlyHint": False},
     "inputSchema": {"type": "object", "properties": {"size": {"type": "integer"}}}},
    {"name": "occupancy", "annotations": {"readOnlyHint": True}, "inputSchema": {"type": "object"}},
    {"name": "describe", "inputSchema": {"type": "object"}},
]


class FakeService:
    def __init__(self, tools, fail=False):
        self.tools, self.fail, self.calls = tools, fail, []

    def list_tools(self):
        if self.fail:
            raise OSError("connection refused")
        return self.tools

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return {"tables": [{"id": "T4", "state": "dirty"}]} if name == "get_tables" else {"ok": True}


def _catalog_with(service: FakeService, server: str = "table-occupancy-service", **kwargs):
    catalog = CapabilityCatalog()
    with patch.object(discovery, "_client", return_value=service):
        errors = discovery.discover(catalog, {server: {"url": "http://table/mcp"}}, **kwargs)
    return catalog, errors


class DiscoveryTests(unittest.TestCase):
    def test_connected_server_registers_reads_and_approval_gated_actions(self):
        service = FakeService(TABLE_TOOLS)
        catalog, errors = _catalog_with(service)
        self.assertEqual(errors, {})
        tools = {name: (tool.read_only, tool.required_reads) for name, tool in catalog.tools.items()}
        prefix = "table-occupancy-service."
        self.assertEqual(tools, {
            prefix + "get_tables": (True, ()), prefix + "get_table": (True, ()), prefix + "occupancy": (True, ()),
            prefix + "describe": (True, ()),
            # Actions require the service's argument-free context reads.
            prefix + "mark_table_cleared": (False, (prefix + "get_tables", prefix + "occupancy")),
            prefix + "seat_party": (False, (prefix + "get_tables", prefix + "occupancy"))})
        live = {prefix + "get_tables": {}, prefix + "occupancy": {}}
        catalog.validate_action(prefix + "mark_table_cleared", {"table_id": "T4"}, live)
        with self.assertRaises(ValueError):  # the service's own schema still applies
            catalog.validate_action(prefix + "mark_table_cleared", {"table": "T4"}, live)
        self.assertEqual(catalog.read(prefix + "get_tables", {}), {"tables": [{"id": "T4", "state": "dirty"}]})
        action = catalog.tools[prefix + "mark_table_cleared"]
        self.assertEqual(action.client.call_tool(action.tool, {"table_id": "T4"}), {"executed": True, "ok": True})

    def test_known_disabled_unreachable_and_read_less_servers(self):
        catalog, _ = _catalog_with(FakeService(TABLE_TOOLS), disabled=["table-occupancy-service.seat_party"])
        self.assertNotIn("table-occupancy-service.seat_party", catalog.tools)
        # Without a context read the actions are not proposable (chat calls are still journaled).
        catalog, _ = _catalog_with(FakeService([TABLE_TOOLS[2]]), server="signage")
        self.assertEqual(catalog.tools, {})
        # Built-in services already in the catalog are left alone.
        catalog, _ = _catalog_with(FakeService(TABLE_TOOLS), server="order-accuracy")
        with patch.object(discovery, "_client", side_effect=AssertionError("not rediscovered")):
            discovery.discover(catalog, {"order-accuracy": {"url": "http://x/mcp"}})
        # An unreachable service is retried after the back-off.
        offline = FakeService(TABLE_TOOLS, fail=True)
        catalog, errors = _catalog_with(offline)
        self.assertIn("connection refused", errors["table-occupancy-service"])
        with patch.object(discovery, "_client", return_value=FakeService(TABLE_TOOLS)):
            discovery.discover(catalog, {"table-occupancy-service": {"url": "http://table/mcp"}})
            self.assertEqual(catalog.tools, {})
            with patch.object(discovery, "RETRY_SECONDS", 0):
                discovery.discover(catalog, {"table-occupancy-service": {"url": "http://table/mcp"}})
        self.assertIn("table-occupancy-service.mark_table_cleared", catalog.tools)

    def test_chat_calls_from_any_connected_server_are_journaled_by_service(self):
        catalog, _ = _catalog_with(FakeService(TABLE_TOOLS))
        servers = {"table-occupancy-service": {}, "kiosk": {}, "order-accuracy": {}, "Digital_Signage": {}}
        calls = [{"tool": "mcp__kiosk__get_kiosk_context", "arguments": {}},
                 {"tool": "mcp__kiosk__update_kiosk_settings", "arguments": {"mode": "express"}},
                 {"tool": "mcp__order_accuracy__request_remake", "arguments": {"order_id": "A-1"}},
                 {"tool": "mcp__edgemart_table_sim_service__mark_table_cleared", "arguments": {"table_id": "T4"}},
                 {"tool": "mcp__edgemart_table_sim_service__occupancy", "arguments": {}},
                 {"tool": "mcp__Digital_Signage__show_promo", "arguments": {"promo": "soup"}},
                 {"tool": "memory", "arguments": {"action": "add"}}]
        self.assertEqual(discovery.chat_action_calls(calls, catalog, servers), [
            {"tool": "kiosk.update_kiosk_settings", "arguments": {"mode": "express"}},
            {"tool": "accuracy.request_remake", "arguments": {"order_id": "A-1"}},
            {"tool": "table-occupancy-service.mark_table_cleared", "arguments": {"table_id": "T4"}},
            {"tool": "digital-signage.show_promo", "arguments": {"promo": "soup"}}])
        self.assertTrue(discovery.is_connected_action("digital-signage.show_promo", catalog, servers))
        self.assertFalse(discovery.is_connected_action("digital-signage.get_promos", catalog, servers))
        self.assertFalse(discovery.is_connected_action("table-occupancy-service.occupancy", catalog, servers))
        self.assertFalse(discovery.is_connected_action("shell.run", catalog, servers))

    def test_discovered_service_is_learnable_without_service_code(self):
        catalog, _ = _catalog_with(FakeService(TABLE_TOOLS))
        tools = catalog_tools(catalog)
        records = []
        for index in range(8):
            table, minutes = f"table-{index}", 5 + index * 3  # 5..26 minutes dirty; cleared from 14 up
            event = {"event_id": f"t-{index}", "service": "table-occupancy-service", "event_type": "table_dirty",
                     "occurred_at": f"2026-11-02T10:{index:02d}:00+00:00",
                     "data": {"table_id": table, "minutes_dirty": minutes}}
            calls = ([{"tool": "table-occupancy-service.mark_table_cleared", "arguments": {"table_id": table}}]
                     if minutes >= 14 else [])
            records.append(service_record(event, "instruction" if calls else "none", "", calls, None, f"t-{index}"))
        accepted, dropped = verify_rules(induce_missing_rules([], records), records, tools)
        self.assertEqual(len(accepted), 1, dropped)
        self.assertEqual(matching_settings(accepted, {"event.table_id": "table-9", "event.minutes_dirty": 30}),
                         {"table-occupancy-service.mark_table_cleared": {"table_id": "table-9"}})
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "learned-table-occupancy-service/SKILL.md"
            skill.parent.mkdir()
            skill.write_text(render_skill("table-occupancy-service", accepted, tools), encoding="utf-8")
            self.assertEqual(register_learned_skills(catalog, Path(directory)), {})
        self.assertIn("table-occupancy-service.get_tables",
                      catalog.skills["learned-table-occupancy-service"].tools)

    def test_hermes_config_and_text_only_results(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("mcp_servers:\n  a: {url: http://a/mcp}\n  b: {url: http://b/mcp, enabled: false}\n"
                              "  c: {command: python, args: [server.py]}\n  d: {}\n", encoding="utf-8")
            self.assertEqual(sorted(discovery.hermes_servers(config)), ["a", "c"])
            self.assertEqual(discovery.hermes_servers(Path(directory) / "missing.yaml"), {})
        self.assertEqual(discovery.service_prefix("Digital_Signage 2"), "digital-signage-2")
        self.assertEqual(_structured("t", {"content": [{"type": "text", "text": json.dumps({"a": 1})}]}), {"a": 1})
        self.assertEqual(_structured("t", {"content": [{"type": "text", "text": "Table T4 cleared"}]}),
                         {"text": "Table T4 cleared"})
        with self.assertRaises(RuntimeError):
            _structured("t", {"isError": True, "content": [{"type": "text", "text": "no such table"}]})


if __name__ == "__main__":
    unittest.main()
