#!/usr/bin/env python3
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class StdioMcpServer:
    def __init__(self, name: str, tools: list[dict[str, Any]], handlers: dict[str, ToolHandler]):
        self.name = name
        self.tools = tools
        self.handlers = handlers
        log_dir = Path(os.environ.get("MCP_LOG_DIR", Path(__file__).parent / "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{name}.jsonl"

    def run(self) -> None:
        self._log("server_started", tools=[tool["name"] for tool in self.tools])
        for line in sys.stdin:
            request: dict[str, Any] | None = None
            try:
                request = json.loads(line)
                response = self._handle(request)
                if response is not None:
                    self._send(response)
            except Exception as error:
                request_id = request.get("id") if isinstance(request, dict) else None
                self._log(
                    "request_failed",
                    request_id=request_id,
                    error_type=type(error).__name__,
                    error=str(error),
                )
                if request_id is not None:
                    self._send(self._error(request_id, -32603, str(error)))
        self._log("server_stopped")

    def _handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        self._log("request_received", request_id=request_id, method=method)

        if method == "initialize":
            return self._result(
                request_id,
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": "0.1.0"},
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return self._result(request_id, {})
        if method == "tools/list":
            self._log("tools_listed", request_id=request_id, count=len(self.tools))
            return self._result(request_id, {"tools": self.tools})
        if method == "tools/call":
            params = request.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            handler = self.handlers.get(name)
            if handler is None:
                self._log("tool_failed", request_id=request_id, tool=name, error="unknown_tool")
                return self._error(request_id, -32602, f"Unknown tool: {name}")
            started_at = time.monotonic()
            self._log("tool_called", request_id=request_id, tool=name, arguments=arguments)
            payload = handler(arguments)
            self._log(
                "tool_succeeded",
                request_id=request_id,
                tool=name,
                duration_ms=round((time.monotonic() - started_at) * 1000, 3),
                placeholder=payload.get("placeholder", False),
            )
            return self._result(
                request_id,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(payload, indent=2)}
                    ],
                    "structuredContent": payload,
                    "isError": False,
                },
            )
        if request_id is None:
            return None
        return self._error(request_id, -32601, f"Method not found: {method}")

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    @staticmethod
    def _send(response: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    def _log(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "server": self.name,
            "pid": os.getpid(),
            "event": event,
            **fields,
        }
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, separators=(",", ":")) + "\n")
