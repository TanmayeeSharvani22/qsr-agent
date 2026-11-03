from __future__ import annotations

import os
from pathlib import Path

from .advisor import HermesRunner
from .controller import AutonomyController
from .discovery import discover, hermes_servers
from .event_agent import HermesEventAgent
from .learning import learning_dir
from .mcp import HttpMcpClient
from .registry import AutonomyRegistry, load_extensions
from .store import ProposalStore
from .service_capabilities import MergedAccuracyClient, register_defaults, register_learned_skills


def build_registry(project_root: Path) -> AutonomyRegistry:
    """Catalog of tools and skills, including approved learned skills."""
    registry = AutonomyRegistry()
    registry.catalog.restaurant_id = os.environ.get("QSR_RESTAURANT_ID", "qsr-001")
    # Kiosk and Order Accuracy are remote services; without a URL their capabilities are not registered.
    kiosk_url = os.environ.get("QSR_KIOSK_MCP_URL", "").strip()
    kiosk_client = HttpMcpClient(kiosk_url) if kiosk_url else None
    accuracy_urls = [url for url in (os.environ.get(f"QSR_ORDER_ACCURACY_{venue}_MCP_URL", "").strip()
                                     for venue in ("TAKE_AWAY", "DINE_IN")) if url]
    accuracy_client = (
        MergedAccuracyClient([HttpMcpClient(url) for url in accuracy_urls]) if len(accuracy_urls) > 1
        else HttpMcpClient(accuracy_urls[0]) if accuracy_urls else None
    )
    weather_url = os.environ.get("QSR_WEATHER_MCP_URL", "http://127.0.0.1:8090/mcp").strip()
    weather_client = HttpMcpClient(weather_url) if weather_url else None
    register_defaults(registry.catalog, project_root, kiosk_client, accuracy_client, weather_client)
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
    discover(registry.catalog, hermes_servers(), disabled_tools)
    register_learned_skills(registry.catalog, learning_dir(project_root) / "skills")
    return registry


def build_controller(root: Path | None = None) -> AutonomyController:
    project_root = root or Path(__file__).resolve().parent.parent
    state_path = Path(
        os.environ.get(
            "QSR_AUTONOMY_DB", Path.home() / ".local/state/qsr-agent/autonomy.db"
        )
    )
    registry = build_registry(project_root)
    learned = learning_dir(project_root) / "skills"
    disabled = [name.strip() for name in os.environ.get("QSR_AUTONOMY_DISABLED_TOOLS", "").split(",")]

    def refresh_skills() -> None:
        # Services that come online later (or were unreachable at start) join without a restart.
        discover(registry.catalog, hermes_servers(), disabled)
        register_learned_skills(registry.catalog, learned)

    registry.register_event(HermesEventAgent(
        HermesRunner(), registry.catalog, refresh_skills=refresh_skills,
    ))
    return registry.build(store=ProposalStore(state_path))