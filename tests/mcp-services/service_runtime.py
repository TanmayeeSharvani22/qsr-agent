#!/usr/bin/env python3
"""Run a QSR MCP service over local stdio or a remote HTTP transport."""

from __future__ import annotations

import os
from typing import Any

from service_bridge import serve
from mcp_service_sdk import ServiceServer


def run_service(
    svc: ServiceServer,
    jsonrpc_name: str,
    tool_schemas: dict[str, dict[str, Any]],
) -> None:
    """Start a service using the transport selected by environment variables.

    QSR_MCP_TRANSPORT accepts ``stdio`` (default), ``streamable-http``, or
    ``sse``. Network transports also use QSR_MCP_HOST and QSR_MCP_PORT.
    """
    for name, schema in tool_schemas.items():
        tool = svc._read_tools.get(name) or svc._act_tools.get(name)
        if tool is not None:
            tool.schema = schema

    transport = os.environ.get("QSR_MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        serve(svc, jsonrpc_name, tool_schemas)
        return
    if transport not in {"streamable-http", "sse"}:
        raise ValueError(
            "QSR_MCP_TRANSPORT must be 'stdio', 'streamable-http', or 'sse'"
        )

    host = os.environ.get("QSR_MCP_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("QSR_MCP_PORT", "8000"))
    except ValueError as error:
        raise ValueError("QSR_MCP_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError("QSR_MCP_PORT must be between 1 and 65535")

    svc.run(transport=transport, host=host, port=port)