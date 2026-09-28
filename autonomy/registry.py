from __future__ import annotations

import importlib
from collections.abc import Iterable
from typing import Any

from .controller import (
    AutonomyController,
    EventPolicy,
    ToolClient,
)
from .store import ProposalStore
from .event_agent import CapabilityCatalog


class ToolRouter:
    def __init__(self) -> None:
        self._clients: dict[str, ToolClient] = {}

    def register(self, client: ToolClient, *tool_names: str) -> None:
        names = [tool_name.strip() for tool_name in tool_names]
        if not names or any(not name for name in names):
            raise ValueError("at least one non-empty tool name is required")
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        conflicts = sorted(name for name in names if name in self._clients)
        if conflicts:
            raise ValueError(f"tool already registered: {conflicts[0]}")
        for name in names:
            self._clients[name] = client

    def require(self, tool_name: str) -> None:
        if tool_name not in self._clients:
            raise ValueError(f"context tool is not registered: {tool_name}")

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        client = self._clients.get(name)
        if client is None:
            supported = ", ".join(sorted(self._clients))
            raise ValueError(f"unregistered tool {name!r}; registered tools: {supported}")
        return client.call_tool(name, arguments)


class AutonomyRegistry:
    def __init__(self) -> None:
        self._router = ToolRouter()
        self.catalog = CapabilityCatalog()
        self._events: list[EventPolicy] = []
        self._policy_ids: set[str] = set()
        self._event_types: set[str] = set()

    def register_service(self, client: ToolClient, *tool_names: str) -> None:
        self._router.register(client, *tool_names)

    def register_event(self, policy: EventPolicy) -> None:
        if policy.event_type in self._event_types:
            raise ValueError(f"event type already registered: {policy.event_type}")
        context_tool = getattr(policy, "context_tool", None)
        if context_tool:
            self._router.require(context_tool)
        self._register_policy_id(policy.policy_id)
        self._event_types.add(policy.event_type)
        self._events.append(policy)

    def build(self, store: ProposalStore) -> AutonomyController:
        self.catalog.validate()
        return AutonomyController(
            client=self._router,
            store=store,
            event_policies=list(self._events),
        )

    def _register_policy_id(self, policy_id: str) -> None:
        if not policy_id.strip():
            raise ValueError("policy_id must not be empty")
        if policy_id in self._policy_ids:
            raise ValueError(f"policy already registered: {policy_id}")
        self._policy_ids.add(policy_id)


def load_extensions(registry: AutonomyRegistry, module_names: Iterable[str]) -> None:
    for module_name in module_names:
        name = module_name.strip()
        if not name:
            continue
        module = importlib.import_module(name)
        register = getattr(module, "register_autonomy", None)
        if not callable(register):
            raise ValueError(f"{name} must define register_autonomy(registry)")
        register(registry)