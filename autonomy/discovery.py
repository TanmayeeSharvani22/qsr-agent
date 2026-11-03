"""Plug-and-play MCP services: every server Hermes is connected to feeds the learning journal and,
when it exposes a context read, becomes available to event decisions and learning without
per-service code. Every discovered action still needs operator approval before it runs.
"""

from __future__ import annotations

import os
import re
import sys
import time
import weakref
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .event_agent import Capability, CapabilityCatalog
from .mcp import HttpMcpClient, StdioMcpClient

# Built-in services whose catalog prefix differs from the Hermes server name.
SERVICE_PREFIXES = {"order-accuracy": "accuracy", "order-accuracy-take-away": "accuracy",
                    "order-accuracy-dine-in": "accuracy"}
READ_PREFIXES = ("get_", "list_", "read_", "search_", "find_", "fetch_", "query_", "describe_", "check_", "lookup_")
# Contract tools every QSR service exposes; read-only even without a hint.
READ_NAMES = {"describe"}
RETRY_SECONDS = 60.0
_seen: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_failed: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def hermes_servers(config: Path | None = None) -> dict[str, dict[str, Any]]:
    """Enabled MCP servers from the Hermes config that the agent was started with."""
    path = config or Path(os.environ.get("HERMES_CONFIG", Path.home() / ".hermes/config.yaml"))
    try:
        servers = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("mcp_servers") or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {name: entry for name, entry in servers.items()
            if isinstance(entry, dict) and entry.get("enabled", True) and (entry.get("url") or entry.get("command"))}


def service_prefix(server: str) -> str:
    """Catalog/journal service name for a Hermes MCP server (lowercase letters, digits, dashes)."""
    if server in SERVICE_PREFIXES:
        return SERVICE_PREFIXES[server]
    name = re.sub(r"[^a-z0-9-]+", "-", server.lower()).lstrip("-0123456789")[:40].rstrip("-")
    return name or "service"


def is_read(tool: dict[str, Any]) -> bool:
    """MCP `readOnlyHint` when the server sets it, else a get_/list_/... name."""
    hint = (tool.get("annotations") or {}).get("readOnlyHint")
    name = str(tool.get("name", ""))
    return hint if isinstance(hint, bool) else name in READ_NAMES or name.startswith(READ_PREFIXES)


def _wire(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def chat_action_calls(calls: list[dict[str, Any]], catalog: CapabilityCatalog,
                      servers: dict[str, Any]) -> list[dict[str, Any]]:
    """State-changing MCP calls from a Hermes chat turn (`mcp__<server>__<tool>`), named `<service>.<tool>`.

    Covers every connected server, registered in the autonomy catalog or not.
    """
    found = []
    for call in calls:
        name = str(call.get("tool") or "")
        for server in servers:
            prefix = f"mcp__{_wire(server)}__"
            if not name.startswith(prefix):
                continue
            raw = name[len(prefix):]
            full = f"{service_prefix(server)}.{raw}"
            known = catalog.tools.get(full)
            if not (known.read_only if known else is_read({"name": raw})):
                found.append({"tool": full, "arguments": call.get("arguments") or {}})
            break
    return found


def is_connected_action(name: Any, catalog: CapabilityCatalog, servers: dict[str, Any]) -> bool:
    """A catalog action, or `<service>.<tool>` of any connected server that is not a read."""
    if not isinstance(name, str) or "." not in name:
        return False
    if name in catalog.tools:
        return not catalog.tools[name].read_only
    service, tool = name.split(".", 1)
    return service in {service_prefix(server) for server in servers} and not is_read({"name": tool})


class _ActionClient:
    """Marks a successful generic MCP action as executed, as built-in services report it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def list_tools(self) -> list[dict[str, Any]]:
        return self.inner.list_tools()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.inner.call_tool(name, arguments)
        return result if "executed" in result else {"executed": True, **result}


def _client(entry: dict[str, Any]) -> Any:
    if entry.get("url"):
        headers = {key: str(value) for key, value in (entry.get("headers") or {}).items()}
        return HttpMcpClient(str(entry["url"]), timeout=min(float(entry.get("timeout", 10)), 10.0), headers=headers)
    args = entry.get("args") or []
    if len(args) == 1:
        return StdioMcpClient(Path(entry["command"]), Path(args[0]))
    return None


def discover(catalog: CapabilityCatalog, servers: dict[str, Any],
             disabled: Iterable[str] = ()) -> dict[str, str]:
    """Register tools of connected servers not yet in the catalog; unreachable ones retry later."""
    errors: dict[str, str] = {}
    seen, failed = _seen.setdefault(catalog, set()), _failed.setdefault(catalog, {})
    skip = set(disabled)
    for server, entry in servers.items():
        prefix = service_prefix(server)
        if server in seen or any(name.startswith(prefix + ".") for name in catalog.tools):
            continue
        if time.monotonic() - failed.get(server, -RETRY_SECONDS) < RETRY_SECONDS:
            continue
        client = _client(entry)
        if client is None:
            continue
        try:
            tools = [tool for tool in client.list_tools() if isinstance(tool.get("name"), str)]
        except (RuntimeError, OSError, ValueError, KeyError) as error:
            failed[server] = time.monotonic()
            errors[server] = str(error)[:200]
            print(f"[autonomy] {server} not discovered yet: {errors[server]}", file=sys.stderr)
            continue
        seen.add(server)
        failed.pop(server, None)
        tools = [tool for tool in tools if f"{prefix}.{tool['name']}" not in skip]
        reads = [tool for tool in tools if is_read(tool)]
        context = tuple(f"{prefix}.{tool['name']}" for tool in reads
                        if tool["name"] not in READ_NAMES and not (tool.get("inputSchema") or {}).get("required"))
        acting = _ActionClient(client)
        for tool in tools:
            name, read = f"{prefix}.{tool['name']}", is_read(tool)
            if name in catalog.tools or not (read or context):
                continue  # actions need a live context read; their chat calls are journaled regardless
            # Discovered actions: the catalog checks the schema and every proposal waits for operator approval.
            catalog.register_tool(Capability(
                name, str(tool.get("description") or tool["name"])[:300], client if read else acting,
                tool["name"], read, () if read else context,
                validate=None if read else (lambda arguments, observations: None), store_scoped=False))
        print(f"[autonomy] discovered {server}: {len(tools)} tools", file=sys.stderr)
    return errors
