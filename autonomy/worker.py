from __future__ import annotations

import os
from pathlib import Path

from .advisor import HermesRunner
from .controller import AutonomyController
from .event_agent import HermesEventAgent
from .mcp import StdioMcpClient
from .registry import AutonomyRegistry, load_extensions
from .store import ProposalStore
from .service_capabilities import register_defaults


def build_controller(root: Path | None = None) -> AutonomyController:
    project_root = root or Path(__file__).resolve().parent.parent
    python = Path(os.environ.get("QSR_MCP_PYTHON", project_root / ".venv/mcp/bin/python"))
    server = Path(
        os.environ.get("QSR_KIOSK_SERVER", project_root / "tests/mcp-services/kiosk_server.py")
    )
    state_path = Path(
        os.environ.get(
            "QSR_AUTONOMY_DB", Path.home() / ".local/state/qsr-agent/autonomy.db"
        )
    )
    registry = AutonomyRegistry()
    registry.catalog.restaurant_id = os.environ.get("QSR_RESTAURANT_ID", "qsr-001")
    kiosk_client = StdioMcpClient(python, server)
    accuracy_client = StdioMcpClient(
        python, Path(os.environ.get(
            "QSR_ACCURACY_SERVER", project_root / "tests/mcp-services/order_accuracy_server.py"
        ))
    )
    register_defaults(registry.catalog, project_root, kiosk_client, accuracy_client)
    load_extensions(
        registry,
        os.environ.get("QSR_AUTONOMY_MODULES", "").split(","),
    )
    disabled_tools = [name.strip() for name in os.environ.get(
        "QSR_AUTONOMY_DISABLED_TOOLS", ""
    ).split(",") if name.strip()]
    registry.catalog.remove_tools(*disabled_tools)
    for name in os.environ.get("QSR_AUTONOMY_DISABLED_SKILLS", "").split(","):
        registry.catalog.remove_skill(name.strip())
    registry.register_event(HermesEventAgent(HermesRunner(), registry.catalog))
    return registry.build(store=ProposalStore(state_path))