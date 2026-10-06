from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .event_agent import Capability, CapabilityCatalog, Skill, StaleContextError


def validate_menu(arguments: dict[str, Any], observations: dict[str, Any]) -> None:
    context = observations["kiosk.get_kiosk_context"]
    _fresh(context)
    items = {item["id"]: item for item in context.get("menu", {}).get("items", [])}
    seen: set[str] = set()
    for change in arguments["changes"]:
        item_id = change["item_id"]
        if item_id not in items or item_id in seen:
            raise ValueError("menu changes require distinct live item IDs")
        if items[item_id]["available"] == change["available"]:
            raise ValueError(f"{item_id} already has the requested availability")
        if not change["reason"].strip():
            raise ValueError("each menu change needs a reason")
        seen.add(item_id)
    if not arguments["reason"].strip():
        raise ValueError("menu action needs a reason")


def validate_remake(arguments: dict[str, Any], observations: dict[str, Any]) -> None:
    context = observations["accuracy.get_order_accuracy_context"]
    _fresh(context)
    order = next((order for order in context.get("recent_orders", [])
                  if order.get("order_id") == arguments["order_id"]), None)
    if not order or order.get("result") != "flagged" or not order.get("issues"):
        raise ValueError("remake requires an exact currently flagged order with issue evidence")
    if not arguments["reason"].strip():
        raise ValueError("remake action needs a reason")


def _fresh(context: dict[str, Any]) -> None:
    observed = datetime.fromisoformat(context.get("observed_at", "").replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("context has an invalid observation time")
    age = (datetime.now(UTC) - observed).total_seconds()
    if age < -30:
        raise ValueError("context has a future observation time")
    if age > 120:
        raise StaleContextError("context is stale")


def register_defaults(
    catalog: CapabilityCatalog, root: Path, kiosk: Any, accuracy: Any, weather: Any | None = None
) -> None:
    catalog.register_tool(Capability(
        "kiosk.get_kiosk_context", "Read current menu, queue, wait, staffing and demand",
        kiosk, "get_kiosk_context", True,
    ))
    catalog.register_tool(Capability(
        "kiosk.change_menu_items", "Propose up to three menu availability changes; no prices",
        kiosk, "change_menu_items", False, ("kiosk.get_kiosk_context",), validate_menu,
    ))
    catalog.register_tool(Capability(
        "accuracy.get_order_accuracy_context", "Read accuracy, flagged orders, mismatches and stations",
        accuracy, "get_order_accuracy_context", True,
    ))
    catalog.register_tool(Capability(
        "accuracy.request_remake", "Propose remaking an exact flagged order",
        accuracy, "request_remake", False, ("accuracy.get_order_accuracy_context",), validate_remake,
    ))
    weather_reads: tuple[str, ...] = ()
    if weather is not None:
        catalog.register_tool(Capability(
            "weather.get_weather_details",
            "Read current store-location weather: condition, is_raining, temperature_c, precipitation",
            weather, "get_weather_details", True, store_scoped=False,
        ))
        weather_reads = ("weather.get_weather_details",)
    for name, description, tools in (
        ("event-menu-decisions", "Weather and queue events: decide whether menu availability should change",
         ("kiosk.get_kiosk_context", "kiosk.change_menu_items", *weather_reads)),
        ("kiosk-operations", "Restaurant operations, menu, queue, wait, staffing and ordering activity",
         ("kiosk.get_kiosk_context", "kiosk.change_menu_items")),
        ("order-accuracy", "Order mismatches, accuracy alerts, station issues and remake recommendations",
         ("accuracy.get_order_accuracy_context", "accuracy.request_remake")),
    ):
        catalog.register_skill(Skill(name, description, root / "qsr-skills" / name / "SKILL.md", tools))