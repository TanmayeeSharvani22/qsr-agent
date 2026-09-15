#!/usr/bin/env python3
"""Adapter for serving a ServiceServer over the test stdio transport.

The QSR placeholders adopt the mcp-service-sdk *contract* (ServiceServer with
declared read/act tools, a deterministic policy gate, durable log, telemetry and
`describe`) while keeping the dependency-free `StdioMcpServer` JSON-RPC transport
used by the simulations. Tool names, JSON-Schema signatures, and JSONL tool-call
logs remain stable for any compatible MCP client.

A service module builds a ServiceServer, then calls `serve(svc, ...)` passing an
explicit JSON Schema per tool (the authoritative signature the agent sees).
"""

from __future__ import annotations

from typing import Any, Callable

from mcp_service_sdk import ServiceServer

from mcp_stdio import StdioMcpServer

EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


def _read_handler(svc: ServiceServer, name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    tool = svc._read_tools[name]

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        result = svc._invoke(tool.fn, arguments)
        return result if isinstance(result, dict) else {"result": result}

    return handler


def _act_handler(svc: ServiceServer, name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        # Route every action through the policy gate — the only path to acting.
        decision = svc.call_action(name, **arguments)
        inner = decision.get("result", {}) or {}
        merged = {"executed": decision["executed"], "gate": decision["level"]}
        if not decision["executed"]:
            merged["reason"] = decision.get("reason", "")
        if isinstance(inner, dict):
            merged.update(inner)
        else:
            merged["result"] = inner
        return merged

    return handler


def serve(svc: ServiceServer, jsonrpc_name: str, tool_schemas: dict[str, dict[str, Any]]) -> None:
    """Expose a ServiceServer's read/act tools (plus `describe`) over stdio.

    tool_schemas maps every read/act tool name to its JSON Schema `inputSchema`.
    This is the exact signature the MCP client receives, so it never guesses args.
    """
    tools: list[dict[str, Any]] = []
    handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    for name, tool in svc._read_tools.items():
        tools.append(
            {
                "name": name,
                "description": tool.description,
                "inputSchema": tool_schemas.get(name, EMPTY_SCHEMA),
            }
        )
        handlers[name] = _read_handler(svc, name)

    for name, tool in svc._act_tools.items():
        gate = svc.policy._actions[name].level.value
        tools.append(
            {
                "name": name,
                "description": f"[gate={gate}] {tool.description}",
                "inputSchema": tool_schemas.get(name, EMPTY_SCHEMA),
            }
        )
        handlers[name] = _act_handler(svc, name)

    tools.append(
        {
            "name": "describe",
            "description": (
                "Return this service's contract: declared event types, read tools, "
                "and gated act tools with their signatures. Call it to learn exactly "
                "which tools exist and how to call them."
            ),
            "inputSchema": EMPTY_SCHEMA,
        }
    )
    handlers["describe"] = lambda _arguments: svc.describe()

    StdioMcpServer(jsonrpc_name, tools, handlers).run()
