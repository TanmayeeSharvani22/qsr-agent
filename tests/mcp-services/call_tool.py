#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def send(process: subprocess.Popen[str], request: dict[str, Any]) -> dict[str, Any]:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    response = process.stdout.readline()
    if not response:
        raise RuntimeError("MCP server stopped without returning a response")
    return json.loads(response)


def main() -> int:
    parser = argparse.ArgumentParser(description="Call a tool on a placeholder stdio MCP server")
    parser.add_argument("server", choices=["kiosk", "order-accuracy"])
    parser.add_argument("tool")
    parser.add_argument("arguments", nargs="?", default="{}", help="JSON object")
    args = parser.parse_args()

    scripts = {
        "kiosk": "kiosk_server.py",
        "order-accuracy": "order_accuracy_server.py",
    }
    server_path = Path(__file__).parent / scripts[args.server]
    arguments = json.loads(args.arguments)

    process = subprocess.Popen(
        [sys.executable, str(server_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "placeholder-smoke-test", "version": "1.0"},
                },
            },
        )
        response = send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": args.tool, "arguments": arguments},
            },
        )
        print(json.dumps(response, indent=2))
        return 1 if "error" in response else 0
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())