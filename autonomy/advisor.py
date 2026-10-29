from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .hermes_gateway import GatewayError, HermesGateway


@dataclass(frozen=True)
class MenuChange:
    item_id: str
    available: bool
    reason: str


@dataclass(frozen=True)
class MenuDecision:
    summary: str
    confidence: float
    changes: tuple[MenuChange, ...]
    raw_response: str


class MenuAdvisor(Protocol):
    def decide(
        self,
        event_type: str,
        event_data: dict[str, Any],
        context: dict[str, Any],
    ) -> MenuDecision: ...


def parse_menu_decision(
    response: str, menu_item_ids: set[str]
) -> MenuDecision:
    text = response.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("Hermes advisor returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("Hermes advisor response must be a JSON object")

    summary = payload.get("summary")
    confidence = payload.get("confidence")
    raw_changes = payload.get("changes")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        raise ValueError("Hermes advisor summary must contain 1-500 characters")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("Hermes advisor confidence must be a number")
    if not 0 <= float(confidence) <= 1:
        raise ValueError("Hermes advisor confidence must be between 0 and 1")
    if not isinstance(raw_changes, list) or len(raw_changes) > 3:
        raise ValueError("Hermes advisor changes must be a list of at most 3 items")

    changes: list[MenuChange] = []
    seen: set[str] = set()
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            raise ValueError("each Hermes menu change must be an object")
        item_id = raw_change.get("item_id")
        available = raw_change.get("available")
        reason = raw_change.get("reason")
        if item_id not in menu_item_ids:
            raise ValueError(f"Hermes advisor returned unknown menu item: {item_id}")
        if item_id in seen:
            raise ValueError(f"Hermes advisor returned duplicate menu item: {item_id}")
        if not isinstance(available, bool):
            raise ValueError("Hermes advisor availability must be a boolean")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
            raise ValueError("Hermes menu-change reason must contain 1-300 characters")
        seen.add(item_id)
        changes.append(MenuChange(item_id, available, reason.strip()))
    return MenuDecision(
        summary.strip(), float(confidence), tuple(changes), response.strip()
    )


class HermesRunner:
    """Event-decision completions on the always-running gateway's events profile.

    That profile sees Hermes's memory read-only and has no tools, so a decision can
    only recommend; actions still go through operator approval.
    """

    def __init__(self, skill_path: Path | None = None, gateway: HermesGateway | None = None) -> None:
        self.timeout = float(os.environ.get("QSR_ADVISOR_TIMEOUT", "90"))
        self.gateway = gateway or HermesGateway.events(self.timeout)
        self.skill_path = skill_path or (
            Path(__file__).resolve().parent.parent
            / "qsr-skills/event-menu-decisions/SKILL.md"
        )
        self._call_lock = threading.Lock()

    def complete(self, prompt: str) -> str:
        with self._call_lock:
            try:
                return self.gateway.complete(prompt)
            except GatewayError as error:
                raise RuntimeError(f"Hermes advisor failed: {error}") from error


class HermesMenuAdvisor(HermesRunner):
    def decide(
        self,
        event_type: str,
        event_data: dict[str, Any],
        context: dict[str, Any],
    ) -> MenuDecision:
        skill = self.skill_path.read_text(encoding="utf-8")
        menu_item_ids = {
            item.get("id") for item in context.get("menu", {}).get("items", [])
            if isinstance(item.get("id"), str)
        }
        if not menu_item_ids:
            raise ValueError("kiosk context contains no menu items")
        return parse_menu_decision(
            self.complete(self._prompt(skill, event_type, event_data, context)),
            menu_item_ids,
        )

    @staticmethod
    def _prompt(
        skill: str,
        event_type: str,
        event_data: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        operations = context.get("operations", {})
        weather = context.get("weather", {})
        activity = context.get("recent_activity", {})
        menu = context.get("menu", {})
        decision_context = {
            "event": {"type": event_type, "data": event_data},
            "state": {
                "queue": operations.get("queue_count"),
                "wait_min": operations.get("estimated_wait_minutes"),
                "staff": operations.get("staff_on_duty"),
                "orders_15m": activity.get("orders_last_15_minutes"),
                "abandoned": activity.get("abandoned_sessions"),
                "weather": {
                    "condition": weather.get("condition"),
                    "raining": weather.get("is_raining"),
                    "temp_c": weather.get("temperature_c"),
                },
                "menu": [
                    {"id": item.get("id"), "available": item.get("available")}
                    for item in menu.get("items", [])
                    if isinstance(item, dict)
                ],
                "observed_at": context.get("observed_at"),
            },
        }
        return (
            "Use this skill to decide a bounded menu recommendation. You have no tools; "
            "recommend only, never execute.\n"
            f"<skill>\n{skill}\n</skill>\n\n"
            f"<state>{json.dumps(decision_context, separators=(',', ':'))}</state>\n"
            "Return ONLY JSON with exactly: "
            '{"summary":"brief overall rationale","confidence":0.0,'
            '"changes":[{"item_id":"an exact live menu id",'
            '"available":true,"reason":"item-specific rationale"}]}. '
            "Use an empty changes list when no menu change is justified."
        )
