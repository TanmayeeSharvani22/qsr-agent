#!/usr/bin/env python3
"""Simulated Order Accuracy service built on the mcp-service-sdk contract.

Declares the `get_order_accuracy_context` read tool plus gated act tools
(`request_remake`, `issue_comp`) on a ServiceServer, then serves them over the
shared stdio transport. Tool names and signatures are stable for any compatible
MCP client.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Import the runtime first so the shared test transport is available.
from service_runtime import run_service

from mcp_service_sdk import GateLevel, ServiceConfig, ServiceServer

STORE_ID = "qsr-001"

ORDER_ACCURACY_CONTEXT = {
    "schema_version": "1.0",
    "source": "order-accuracy-placeholder",
    "restaurant": {"id": "qsr-001", "name": "Demo QSR Restaurant"},
    "summary": {
        "window_minutes": 30,
        "orders_observed": 24,
        "orders_accurate": 21,
        "orders_flagged": 3,
        "accuracy_rate": 0.875,
    },
    "stations": [
        {"id": "station-1", "type": "pickup_counter", "orders": 14, "flagged": 1},
        {"id": "station-2", "type": "drive_through", "orders": 10, "flagged": 2},
    ],
    "recent_orders": [
        {
            "order_id": "ORD-1042",
            "station_id": "station-2",
            "expected_items": ["burger-classic", "fries", "cola"],
            "observed_items": ["burger-classic", "cola"],
            "result": "flagged",
            "issues": [{"type": "missing_item", "item_id": "fries", "confidence": 0.94}],
        },
        {
            "order_id": "ORD-1043",
            "station_id": "station-1",
            "expected_items": ["chicken-wrap", "fries"],
            "observed_items": ["chicken-wrap", "fries"],
            "result": "accurate",
            "issues": [],
        },
        {
            "order_id": "ORD-1044",
            "station_id": "station-2",
            "expected_items": ["burger-classic", "cola"],
            "observed_items": ["burger-classic", "shake"],
            "result": "flagged",
            "issues": [{"type": "wrong_item", "expected": "cola", "observed": "shake", "confidence": 0.89}],
        },
    ],
    "alerts": [
        {
            "severity": "warning",
            "type": "station_accuracy_drop",
            "station_id": "station-2",
            "message": "Drive-through accuracy is below the 90% operating threshold.",
        }
    ],
}

svc = ServiceServer.from_config(
    ServiceConfig(
        service="order-accuracy-placeholder", store_id=STORE_ID, log_backend="memory", metrics="null"
    )
)

svc.register_event_type(
    "order_mismatch",
    schema={"order_id": "str", "station_id": "str", "issues": "list[dict]"},
)


@svc.read_tool(
    "get_order_accuracy_context",
    description=(
        "Return the complete current order-accuracy snapshot, including summary "
        "metrics, station breakdowns, recent expected-versus-observed orders, "
        "detected issues, confidence scores, and alerts. Use it for any "
        "order-accuracy question."
    ),
)
def get_order_accuracy_context() -> dict[str, Any]:
    return {**ORDER_ACCURACY_CONTEXT, "observed_at": datetime.now(UTC).isoformat()}


@svc.act_tool(
    "request_remake",
    level=GateLevel.AUTOMATIC,  # placeholder acknowledges; rate-limited guardrail
    description="Ask the line to remake an order flagged inaccurate. Placeholder only.",
    max_calls=5,
    per_seconds=60.0,
)
def request_remake(order_id: str, reason: str) -> dict[str, Any]:
    return {
        "status": "accepted",
        "action_id": "remake-demo-001",
        "placeholder": True,
        "requested_change": {"order_id": order_id, "reason": reason},
        "message": "Placeholder accepted the remake request; no external line was notified.",
        "executed_at": datetime.now(UTC).isoformat(),
    }


@svc.act_tool(
    "issue_comp",
    level=GateLevel.NEEDS_APPROVAL,  # comps/refunds always human-approved
    description="Issue a comp/refund for an order. Requires human approval. Placeholder only.",
)
def issue_comp(order_id: str, amount: float) -> dict[str, Any]:
    return {
        "status": "accepted",
        "action_id": "comp-demo-001",
        "placeholder": True,
        "requested_change": {"order_id": order_id, "amount": amount},
        "message": "Placeholder issued the comp; no external system was charged.",
        "executed_at": datetime.now(UTC).isoformat(),
    }


TOOL_SCHEMAS = {
    "get_order_accuracy_context": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "request_remake": {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "Order identifier to remake"},
            "reason": {"type": "string", "description": "Why the order needs remaking"},
        },
        "required": ["order_id", "reason"],
        "additionalProperties": False,
    },
    "issue_comp": {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "Order identifier to comp"},
            "amount": {"type": "number", "minimum": 0, "description": "Comp/refund amount"},
        },
        "required": ["order_id", "amount"],
        "additionalProperties": False,
    },
}


if __name__ == "__main__":
    run_service(svc, "order-accuracy-placeholder", TOOL_SCHEMAS)
