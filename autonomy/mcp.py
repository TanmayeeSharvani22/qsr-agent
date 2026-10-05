from __future__ import annotations

import json
import os
import signal
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "qsr-autonomy", "version": "0.1.0"}


class HttpMcpClient:
    """Minimal MCP Streamable HTTP client for remote services such as weather."""

    def __init__(self, url: str, timeout: float = 20.0, headers: dict[str, str] | None = None):
        self._url = url
        self._timeout = timeout
        self._headers = headers or {}
        # Service hosts are internal; a corporate proxy cannot reach them.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            content = result.get("content") or [{}]
            raise RuntimeError(f"MCP tool failed: {name}: {content[0].get('text', '')[:300]}")
        return result["structuredContent"]

    def list_tools(self) -> list[dict[str, Any]]:
        return self._request("tools/list", {})["tools"]

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            _result, session = self._post(None, {
                "jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "initialize",
                "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
            })
            self._post(session, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            response, _ = self._post(session, {
                "jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params,
            })
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"MCP service unavailable at {self._url}: {error}") from error
        if response is None:
            raise RuntimeError(f"MCP service at {self._url} returned no response")
        if "error" in response:
            raise RuntimeError(response["error"].get("message", "MCP request failed"))
        return response["result"]

    def _post(self, session: str | None, message: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        request = urllib.request.Request(
            self._url,
            data=json.dumps(message).encode("utf-8"),
            headers={
                **self._headers,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": PROTOCOL_VERSION,
                **({"Mcp-Session-Id": session} if session else {}),
            },
            method="POST",
        )
        with self._opener.open(request, timeout=self._timeout) as response:
            session = response.headers.get("Mcp-Session-Id") or session
            raw = response.read().decode("utf-8")
        data = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
        payload = "\n".join(data) if data else raw
        return (json.loads(payload) if payload.strip() else None), session


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