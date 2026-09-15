#!/usr/bin/env python3
"""Simulated Kiosk service built on the mcp-service-sdk contract.

Declares one read tool (`get_kiosk_context`) and one gated act tool
(`change_menu`) on a ServiceServer, then serves them over the shared stdio
transport. Tool names and JSON-Schema signatures are stable for any compatible
MCP client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Import the runtime first so the shared test transport is available.
from service_runtime import run_service

from mcp_service_sdk import GateLevel, ServiceConfig, ServiceServer

STORE_ID = "qsr-001"

KIOSK_CONTEXT = {
    "schema_version": "1.0",
    "source": "kiosk-placeholder",
    "restaurant": {
        "id": "qsr-001",
        "name": "Demo QSR Restaurant",
        "location": "Edge Retail Lab",
        "timezone": "America/Los_Angeles",
    },
    "operations": {
        "status": "open",
        "queue_count": 7,
        "estimated_wait_minutes": 6,
        "active_kiosks": 3,
        "staff_on_duty": 8,
    },
    "menu": {
        "active_menu_id": "lunch-standard",
        "items": [
            {"id": "burger-classic", "name": "Classic Burger", "price": 6.99, "available": True},
            {"id": "chicken-wrap", "name": "Chicken Wrap", "price": 7.49, "available": True},
            {"id": "fries", "name": "Fries", "price": 2.99, "available": True},
            {"id": "shake", "name": "Vanilla Shake", "price": 3.99, "available": False},
        ],
    },
    "recent_activity": {
        "orders_last_15_minutes": 18,
        "top_item": "Classic Burger",
        "abandoned_sessions": 2,
    },
}

svc = ServiceServer.from_config(
    ServiceConfig(service="kiosk-placeholder", store_id=STORE_ID, log_backend="memory", metrics="null")
)

svc.register_event_type(
    "menu_changed",
    schema={"item_id": "str", "available": "bool|None", "price": "float|None", "reason": "str"},
)


@svc.read_tool(
    "get_kiosk_context",
    description=(
        "Return a complete snapshot of restaurant identity, current menu, queue, "
        "wait time, staffing, kiosk availability, and recent ordering activity. Use "
        "this broad context tool for kiosk and restaurant-state questions."
    ),
)
def get_kiosk_context() -> dict[str, Any]:
    return {**KIOSK_CONTEXT, "observed_at": datetime.now(UTC).isoformat()}


@svc.act_tool(
    "change_menu",
    level=GateLevel.AUTOMATIC,  # placeholder acknowledges; a real kiosk flips this to needs_approval
    description=(
        "Request a kiosk menu change. This placeholder records and acknowledges the "
        "requested action but does not modify a real kiosk."
    ),
)
def change_menu(
    item_id: str,
    reason: str,
    available: bool | None = None,
    price: float | None = None,
) -> dict[str, Any]:
    requested_change: dict[str, Any] = {"item_id": item_id, "reason": reason}
    if available is not None:
        requested_change["available"] = available
    if price is not None:
        requested_change["price"] = price
    return {
        "status": "accepted",
        "action_id": "menu-change-demo-001",
        "placeholder": True,
        "requested_change": requested_change,
        "message": "Placeholder accepted the menu change; no external kiosk was modified.",
        "executed_at": datetime.now(UTC).isoformat(),
    }


TOOL_SCHEMAS = {
    "get_kiosk_context": {"type": "object", "properties": {}, "additionalProperties": False},
    "change_menu": {
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "description": "Stable menu item identifier"},
            "available": {"type": "boolean", "description": "New availability state"},
            "price": {"type": "number", "minimum": 0, "description": "Optional new price"},
            "reason": {"type": "string", "description": "Operational reason for the change"},
        },
        "required": ["item_id", "reason"],
        "additionalProperties": False,
    },
}


if __name__ == "__main__":
    run_service(svc, "kiosk-placeholder", TOOL_SCHEMAS)
