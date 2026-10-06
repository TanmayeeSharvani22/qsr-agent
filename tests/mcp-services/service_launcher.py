#!/usr/bin/env python3
"""Launch one QSR MCP domain service selected by QSR_SERVICE."""

from __future__ import annotations

import importlib
import os


SERVICES = {
    "kiosk": "kiosk_server",
    "order-accuracy": "order_accuracy_server",
}


def main() -> None:
    service_name = os.environ.get("QSR_SERVICE", "").strip().lower()
    if service_name not in SERVICES:
        available = ", ".join(sorted(SERVICES))
        raise ValueError(f"QSR_SERVICE must be one of: {available}")

    importlib.import_module(SERVICES[service_name]).svc.run()


if __name__ == "__main__":
    main()