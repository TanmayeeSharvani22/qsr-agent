"""FastMCP-based contract for the QSR simulated domain services.

A service declares read tools and policy-gated action tools with explicit JSON
Schemas, then calls `run()`. Every action goes through `PolicyGate`; there is no
path to an action function that bypasses it. Tool calls are logged as JSONL.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.tools.base import ToolResult

EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


class GateLevel(str, Enum):
    AUTOMATIC = "automatic"
    NOTIFY = "notify"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    level: GateLevel
    reason: str


@dataclass
class ActionSpec:
    level: GateLevel
    max_calls: int | None = None
    per_seconds: float = 60.0
    calls: deque[float] = field(default_factory=deque)


class PolicyGate:
    """Deterministic allow-list; the model never decides whether an action runs."""

    def __init__(self, approver: Callable[[str, dict[str, Any]], bool] | None = None) -> None:
        self._actions: dict[str, ActionSpec] = {}
        self._approver = approver or (lambda _name, _arguments: False)

    def register(self, name: str, spec: ActionSpec) -> None:
        self._actions[name] = spec

    def level(self, name: str) -> GateLevel:
        spec = self._actions.get(name)
        return spec.level if spec else GateLevel.BLOCKED

    def evaluate(self, name: str, arguments: dict[str, Any]) -> PolicyDecision:
        spec = self._actions.get(name)
        if spec is None:
            return PolicyDecision(False, GateLevel.BLOCKED, "not on allow-list")
        if spec.level is GateLevel.BLOCKED:
            return PolicyDecision(False, spec.level, "action is blocked")
        if spec.level is GateLevel.NOTIFY:
            return PolicyDecision(False, spec.level, "notify-only, no action")
        if not self._within_rate_limit(spec):
            return PolicyDecision(False, spec.level, "rate limit exceeded")
        if spec.level is GateLevel.NEEDS_APPROVAL:
            if self._approver(name, arguments):
                return PolicyDecision(True, spec.level, "human approved")
            return PolicyDecision(False, spec.level, "awaiting human approval")
        return PolicyDecision(True, spec.level, "auto-approved")

    @staticmethod
    def _within_rate_limit(spec: ActionSpec) -> bool:
        if spec.max_calls is None:
            return True
        now = time.monotonic()
        while spec.calls and spec.calls[0] < now - spec.per_seconds:
            spec.calls.popleft()
        if len(spec.calls) >= spec.max_calls:
            return False
        spec.calls.append(now)
        return True


class _SchemaTool(Tool):
    """FastMCP tool that keeps the service's exact JSON Schema signature."""

    handler: Callable[[dict[str, Any]], dict[str, Any]]

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            payload = await asyncio.to_thread(self.handler, arguments)
        except (ValueError, TypeError) as error:
            raise ToolError(str(error)) from error
        return ToolResult(content=json.dumps(payload, indent=2), structured_content=payload)


@dataclass
class _Registered:
    fn: Callable[..., dict[str, Any]]
    description: str
    schema: dict[str, Any]


class QsrService:
    def __init__(self, name: str, store_id: str, policy: PolicyGate | None = None) -> None:
        self.name = name
        self.store_id = store_id
        self.policy = policy or PolicyGate()
        self.event_types: dict[str, dict[str, Any]] = {}
        self.read_tools: dict[str, _Registered] = {}
        self.act_tools: dict[str, _Registered] = {}

    @property
    def log_path(self) -> Path:
        log_dir = Path(os.environ.get("MCP_LOG_DIR", Path(__file__).parent / "logs"))
        return log_dir / f"{self.name}.jsonl"

    def register_event_type(self, name: str, schema: dict[str, Any]) -> None:
        self.event_types[name] = schema

    def read_tool(self, name: str, description: str, schema: dict[str, Any] | None = None):
        def decorator(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
            self.read_tools[name] = _Registered(fn, description, schema or EMPTY_SCHEMA)
            return fn
        return decorator

    def act_tool(
        self,
        name: str,
        level: GateLevel,
        description: str,
        schema: dict[str, Any] | None = None,
        max_calls: int | None = None,
        per_seconds: float = 60.0,
    ):
        def decorator(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
            self.act_tools[name] = _Registered(fn, description, schema or EMPTY_SCHEMA)
            self.policy.register(name, ActionSpec(level, max_calls, per_seconds))
            return fn
        return decorator

    def set_schemas(self, schemas: dict[str, dict[str, Any]]) -> None:
        """Attach the authoritative JSON Schema the MCP client sees for each tool."""
        for name, schema in schemas.items():
            tool = self.read_tools.get(name) or self.act_tools.get(name)
            if tool is None:
                raise ValueError(f"schema provided for unknown tool: {name}")
            tool.schema = schema

    def call_action(self, name: str, **arguments: Any) -> dict[str, Any]:
        """Run an action through the policy gate; the only path to acting."""
        decision = self.policy.evaluate(name, arguments)
        if not decision.allowed:
            return {"executed": False, "gate": decision.level.value, "reason": decision.reason}
        result = self.act_tools[name].fn(**arguments)
        return {"executed": True, "gate": decision.level.value, **result}

    def describe(self) -> dict[str, Any]:
        return {
            "service": self.name,
            "store_id": self.store_id,
            "event_types": self.event_types,
            "read_tools": {
                name: {"description": tool.description, "schema": tool.schema}
                for name, tool in self.read_tools.items()
            },
            "act_tools": {
                name: {
                    "description": tool.description,
                    "schema": tool.schema,
                    "gate": self.policy.level(name).value,
                }
                for name, tool in self.act_tools.items()
            },
        }

    def build(self) -> FastMCP:
        app = FastMCP(self.name)
        for name, tool in self.read_tools.items():
            app.add_tool(_SchemaTool(
                name=name, description=tool.description, parameters=tool.schema,
                handler=self._logged(name, lambda arguments, fn=tool.fn: fn(**arguments)),
            ))
        for name, tool in self.act_tools.items():
            app.add_tool(_SchemaTool(
                name=name,
                description=f"[gate={self.policy.level(name).value}] {tool.description}",
                parameters=tool.schema,
                handler=self._logged(name, lambda arguments, name=name: self.call_action(name, **arguments)),
            ))
        app.add_tool(_SchemaTool(
            name="describe",
            description=(
                "Return this service's contract: declared event types, read tools, "
                "and gated act tools with their signatures. Call it to learn exactly "
                "which tools exist and how to call them."
            ),
            parameters=EMPTY_SCHEMA,
            handler=self._logged("describe", lambda _arguments: self.describe()),
        ))
        return app

    def run(self) -> None:
        """Serve over QSR_MCP_TRANSPORT: stdio (default), streamable-http/http, or sse."""
        transport = os.environ.get("QSR_MCP_TRANSPORT", "stdio").strip().lower()
        app = self.build()
        self._log("server_started", transport=transport,
                  tools=[*self.read_tools, *self.act_tools, "describe"])
        if transport == "stdio":
            app.run("stdio", show_banner=False)
            return
        if transport not in {"streamable-http", "http", "sse"}:
            raise ValueError("QSR_MCP_TRANSPORT must be 'stdio', 'streamable-http', or 'sse'")
        host = os.environ.get("QSR_MCP_HOST", "127.0.0.1")
        try:
            port = int(os.environ.get("QSR_MCP_PORT", "8000"))
        except ValueError as error:
            raise ValueError("QSR_MCP_PORT must be an integer") from error
        if not 1 <= port <= 65535:
            raise ValueError("QSR_MCP_PORT must be between 1 and 65535")
        app.run("sse" if transport == "sse" else "http", show_banner=False, host=host, port=port)

    def _logged(self, name: str, call: Callable[[dict[str, Any]], dict[str, Any]]):
        def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            started = time.monotonic()
            self._log("tool_called", tool=name, arguments=arguments)
            try:
                payload = call(arguments)
            except Exception as error:
                self._log("tool_failed", tool=name, error_type=type(error).__name__, error=str(error))
                raise
            self._log("tool_succeeded", tool=name,
                      duration_ms=round((time.monotonic() - started) * 1000, 3),
                      placeholder=payload.get("placeholder", False))
            return payload
        return handler

    def _log(self, event: str, **fields: Any) -> None:
        record = {"timestamp": datetime.now(UTC).isoformat(), "server": self.name,
                  "pid": os.getpid(), "event": event, **fields}
        log_path = self.log_path
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
        except OSError:
            pass  # logging must never break a tool call (e.g. read-only image paths)
