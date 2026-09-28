#!/usr/bin/env python3
"""Simulated Kiosk service built on the mcp-service-sdk contract.

Declares one read tool (`get_kiosk_context`) and gated menu action tools on a
ServiceServer, then serves them over the shared stdio transport. Tool names and
JSON-Schema signatures are stable for any compatible MCP client.
"""

from __future__ import annotations

import os
import json
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import fcntl

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
    "weather": {
        "condition": "rain",
        "is_raining": True,
        "temperature_c": 14.0,
        "source": "kiosk-weather-placeholder",
    },
    "menu": {
        "active_menu_id": "lunch-standard",
        "items": [
            {"id": "burger-classic", "name": "Classic Burger", "price": 6.99, "available": True},
            {"id": "chicken-wrap", "name": "Chicken Wrap", "price": 7.49, "available": True},
            {"id": "fries", "name": "Fries", "price": 2.99, "available": True},
            {"id": "shake", "name": "Vanilla Shake", "price": 3.99, "available": False},
            {"id": "hot-chocolate", "name": "Hot Chocolate", "price": 3.49, "available": False},
            {"id": "tea", "name": "Tea", "price": 2.49, "available": False},
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

def _state_path() -> Path:
    return Path(
        os.environ.get(
            "QSR_KIOSK_STATE",
            Path.home() / ".local/state/qsr-agent/kiosk-state.json",
        )
    )


def _read_kiosk_state() -> dict[str, Any]:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_SH)
        try:
            if not path.exists():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _read_menu_overrides() -> dict[str, dict[str, Any]]:
    return _read_kiosk_state().get("menu_items", {})


def _write_menu_override(item_id: str, change: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            menu_items = state.setdefault("menu_items", {})
            menu_items.setdefault(item_id, {}).update(change)
            temporary = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
            temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
            temporary.replace(path)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _write_menu_changes(changes: list[dict[str, Any]]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            menu_items = state.setdefault("menu_items", {})
            for change in changes:
                menu_items.setdefault(change["item_id"], {}).update({
                    "available": change["available"],
                    "availability_reason": change["reason"],
                })
            temporary = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
            temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
            temporary.replace(path)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _resolve_item_id(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        item["id"]: item["id"] for item in KIOSK_CONTEXT["menu"]["items"]
    }
    aliases.update({
        item["name"].lower().replace(" ", "-"): item["id"]
        for item in KIOSK_CONTEXT["menu"]["items"]
    })
    try:
        return aliases[normalized]
    except KeyError as error:
        allowed = ", ".join(item["id"] for item in KIOSK_CONTEXT["menu"]["items"])
        raise ValueError(f"Unknown menu item: {value}. Allowed item IDs: {allowed}") from error


def _simulated_weather(now: float | None = None) -> dict[str, Any]:
    toggle_seconds = float(os.environ.get("QSR_WEATHER_TOGGLE_SECONDS", "30"))
    if toggle_seconds <= 0:
        raise ValueError("QSR_WEATHER_TOGGLE_SECONDS must be greater than zero")
    current_time = time.time() if now is None else now
    period = int(current_time // toggle_seconds)
    is_raining = period % 2 == 0
    return {
        "condition": "rain" if is_raining else "clear",
        "is_raining": is_raining,
        "temperature_c": 14.0 if is_raining else 18.0,
        "source": "kiosk-weather-simulator",
        "simulation_interval_seconds": toggle_seconds,
        "next_change_at": datetime.fromtimestamp(
            (period + 1) * toggle_seconds, UTC
        ).isoformat(),
    }


@svc.read_tool(
    "get_kiosk_context",
    description=(
        "Return a complete snapshot of restaurant identity, current menu, queue, "
        "wait time, staffing, kiosk availability, and recent ordering activity. Use "
        "this broad context tool for kiosk and restaurant-state questions."
    ),
)
def get_kiosk_context() -> dict[str, Any]:
    context = deepcopy(KIOSK_CONTEXT)
    state = _read_kiosk_state()
    overrides = state.get("menu_items", {})
    for item in context["menu"]["items"]:
        item.update(overrides.get(item["id"], {}))
    for field, variable in (
        ("queue_count", "QSR_QUEUE_COUNT"),
        ("estimated_wait_minutes", "QSR_ESTIMATED_WAIT_MINUTES"),
    ):
        if variable in os.environ:
            value = int(os.environ[variable])
            if value < 0:
                raise ValueError(f"{variable} must be nonnegative")
            context["operations"][field] = value
    context["weather"] = _simulated_weather()
    condition = os.environ.get("QSR_WEATHER_CONDITION")
    if condition:
        context["weather"]["condition"] = condition.lower()
        context["weather"]["is_raining"] = condition.lower() in {
            "rain", "raining", "drizzle", "storm"
        }
    context["observed_at"] = datetime.now(UTC).isoformat()
    return context


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
    item_id = _resolve_item_id(item_id)
    if available is None and price is None:
        raise ValueError("At least one of available or price is required")

    requested_change: dict[str, Any] = {"item_id": item_id, "reason": reason}
    persisted_change: dict[str, Any] = {}
    if available is not None:
        requested_change["available"] = available
        persisted_change["available"] = available
        persisted_change["availability_reason"] = reason
    if price is not None:
        requested_change["price"] = price
        persisted_change["price"] = price
    _write_menu_override(item_id, persisted_change)
    return {
        "status": "accepted",
        "action_id": f"menu-change-demo-{uuid4().hex}",
        "placeholder": True,
        "requested_change": requested_change,
        "message": "Placeholder menu state updated; no external kiosk was modified.",
        "executed_at": datetime.now(UTC).isoformat(),
    }


@svc.act_tool(
    "change_menu_items",
    level=GateLevel.AUTOMATIC,
    description=(
        "Apply one approved bundle of up to three menu availability changes. "
        "The bundle is validated and persisted atomically."
    ),
)
def change_menu_items(changes: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    if not isinstance(changes, list) or not 1 <= len(changes) <= 3:
        raise ValueError("changes must contain between one and three items")
    normalized_changes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("each menu change must be an object")
        item_id = _resolve_item_id(str(change.get("item_id", "")))
        if item_id in seen:
            raise ValueError(f"Duplicate menu item: {item_id}")
        available = change.get("available")
        item_reason = change.get("reason")
        if not isinstance(available, bool):
            raise ValueError("each menu change requires boolean available")
        if not isinstance(item_reason, str) or not item_reason.strip():
            raise ValueError("each menu change requires a reason")
        seen.add(item_id)
        normalized_changes.append(
            {
                "item_id": item_id,
                "available": available,
                "reason": item_reason.strip(),
            }
        )
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required")
    _write_menu_changes(normalized_changes)
    return {
        "status": "accepted",
        "action_id": f"menu-bundle-demo-{uuid4().hex}",
        "placeholder": True,
        "changes": normalized_changes,
        "reason": reason.strip(),
        "message": "Placeholder menu items updated; no external kiosk was modified.",
        "executed_at": datetime.now(UTC).isoformat(),
    }


TOOL_SCHEMAS = {
    "get_kiosk_context": {"type": "object", "properties": {}, "additionalProperties": False},
    "change_menu": {
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "enum": ["burger-classic", "chicken-wrap", "fries", "shake", "hot-chocolate", "tea"],
                "description": "Stable menu item identifier from get_kiosk_context",
            },
            "available": {"type": "boolean", "description": "New availability state"},
            "price": {"type": "number", "minimum": 0, "description": "Optional new price"},
            "reason": {"type": "string", "description": "Operational reason for the change"},
        },
        "required": ["item_id", "reason"],
        "additionalProperties": False,
    },
    "change_menu_items": {
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {
                            "type": "string",
                            "enum": ["burger-classic", "chicken-wrap", "fries", "shake", "hot-chocolate", "tea"],
                        },
                        "available": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["item_id", "available", "reason"],
                    "additionalProperties": False,
                },
            },
            "reason": {"type": "string", "description": "Overall advisor rationale"},
        },
        "required": ["changes", "reason"],
        "additionalProperties": False,
    },
}


if __name__ == "__main__":
    run_service(svc, "kiosk-placeholder", TOOL_SCHEMAS)
