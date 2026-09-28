from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .advisor import MenuAdvisor
from .models import PolicyEvaluation, ProposedAction


@dataclass(frozen=True)
class HermesEventMenuPolicy:
    advisor: MenuAdvisor
    policy_id: str
    event_type: str
    context_tool: str = "get_kiosk_context"

    def evaluate_event(
        self, event: dict[str, Any], was_active: bool
    ) -> PolicyEvaluation:
        data = event.get("data")
        if not isinstance(data, dict):
            raise ValueError("data must be an object")
        self._validate_event_data(data)

        context = deepcopy(event.get("context", {}))
        if self.event_type == "weather_changed":
            context.setdefault("weather", {}).update(data)
        elif self.event_type == "queue_count_changed":
            context.setdefault("operations", {})["queue_count"] = data["queue_count"]
        menu_items = context.get("menu", {}).get("items", [])
        current_availability = {
            item.get("id"): item.get("available")
            for item in menu_items
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("available"), bool)
        }
        if not current_availability:
            raise ValueError("kiosk context contains no valid menu items")

        decision = self.advisor.decide(self.event_type, data, context)
        changes = [
            change
            for change in decision.changes
            if current_availability.get(change.item_id) != change.available
        ]
        if not changes:
            return PolicyEvaluation(active=False)

        arguments = {
            "changes": [
                {
                    "item_id": change.item_id,
                    "available": change.available,
                    "reason": change.reason,
                }
                for change in changes
            ],
            "reason": f"Hermes advisor: {decision.summary}",
        }
        proposal = ProposedAction(
            policy_id=self.policy_id,
            trigger_type="hermes",
            summary=decision.summary,
            evidence={
                "event_id": event["event_id"],
                "event_type": self.event_type,
                "decision_source": "hermes",
                "confidence": decision.confidence,
                "changes": arguments["changes"],
                "event_data": data,
                "observed_at": event.get("occurred_at") or context.get("observed_at"),
                "raw_response": decision.raw_response,
            },
            tool="change_menu_items",
            arguments=arguments,
        )
        return PolicyEvaluation(active=True, proposal=proposal)

    def _validate_event_data(self, data: dict[str, Any]) -> None:
        if self.event_type == "weather_changed":
            if not isinstance(data.get("is_raining"), bool):
                raise ValueError("data.is_raining must be a boolean")
            condition = data.get("condition")
            if condition is not None and not isinstance(condition, str):
                raise ValueError("data.condition must be a string")
            return
        if self.event_type == "queue_count_changed":
            queue_count = data.get("queue_count")
            if (
                isinstance(queue_count, bool)
                or not isinstance(queue_count, int)
                or queue_count < 0
            ):
                raise ValueError("data.queue_count must be a non-negative integer")
            return
        raise ValueError(f"unsupported Hermes menu event type: {self.event_type}")