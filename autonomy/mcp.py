from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any


class StdioMcpClient:
    def __init__(self, python: Path, server: Path):
        self._python = python
        self._server = server

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            raise RuntimeError(f"MCP tool failed: {name}")
        return result["structuredContent"]

    def list_tools(self) -> list[dict[str, Any]]:
        return self._request("tools/list", {})["tools"]

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        process = subprocess.Popen(
            [str(self._python), str(self._server)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            requests = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "qsr-autonomy", "version": "0.1.0"},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": method,
                    "params": params,
                },
            ]
            stdout, stderr = process.communicate(
                "".join(json.dumps(request) + "\n" for request in requests), timeout=20
            )
            responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            response = next((item for item in responses if item.get("id") == 2), None)
            if response is None:
                raise RuntimeError(stderr.strip()[:500] or "MCP server stopped without responding")
            if "error" in response:
                raise RuntimeError(response["error"].get("message", "MCP tool call failed"))
            return response["result"]
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("MCP request timed out after 20 seconds") from error
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()