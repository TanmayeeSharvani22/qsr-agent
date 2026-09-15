#!/usr/bin/env python3
"""Launch one QSR MCP domain service selected by QSR_SERVICE."""

from __future__ import annotations

import importlib
import os

from service_runtime import run_service


SERVICES = {
    "kiosk": ("kiosk_server", "kiosk-placeholder"),
    "order-accuracy": ("order_accuracy_server", "order-accuracy-placeholder"),
}


def main() -> None:
    service_name = os.environ.get("QSR_SERVICE", "").strip().lower()
    if service_name not in SERVICES:
        available = ", ".join(sorted(SERVICES))
        raise ValueError(f"QSR_SERVICE must be one of: {available}")

    module_name, jsonrpc_name = SERVICES[service_name]
    module = importlib.import_module(module_name)
    run_service(module.svc, jsonrpc_name, module.TOOL_SCHEMAS)


if __name__ == "__main__":
    main()