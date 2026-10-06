#!/usr/bin/env python3
"""Initialize persistent Hermes configuration and launch the QSR operator UI."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


ROOT = Path("/opt/qsr")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
HERMES_CONFIG = Path(os.environ.get("HERMES_CONFIG", str(HERMES_HOME / "config.yaml")))
MODEL_ID = os.environ.get("MODEL_ID", "OpenVINO/Qwen3-8B-int4-ov")
MODEL_URL = os.environ.get("QSR_MODEL_BASE_URL", "http://ovms:8000/v3")


def _merge(current: Any, update: Any) -> Any:
    if isinstance(current, dict) and isinstance(update, dict):
        result = dict(current)
        for key, value in update.items():
            result[key] = _merge(result[key], value) if key in result else value
        return result
    if isinstance(current, list) and isinstance(update, list):
        return current + [item for item in update if item not in current]
    return update


def _replace_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _replace_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_paths(item) for item in value]
    if isinstance(value, str):
        return value.replace("/absolute/path/to/qsr-agentic-svc", str(ROOT))
    return value


# Expands ${VAR} and ${VAR:-default} from the environment; unset/empty -> default or "".
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, str):
        def _sub(match: re.Match[str]) -> str:
            env_value = os.environ.get(match.group(1))
            if env_value:
                return env_value
            return match.group(2) or ""
        return _ENV_PATTERN.sub(_sub, value)
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def configure_hermes() -> None:
    HERMES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    config = _load_yaml(HERMES_CONFIG) if HERMES_CONFIG.exists() else {}
    for fragment in (
        ROOT / "agent-config/hermes/config.example.yaml",
        ROOT / "agent-config/hermes/remote-mcp.example.yaml",
    ):
        config = _merge(config, _expand_env(_replace_paths(_load_yaml(fragment))))

    config.setdefault("model", {}).update(
        {"default": MODEL_ID, "provider": "custom", "base_url": MODEL_URL}
    )
    config.setdefault("providers", {}).setdefault("custom", {})["base_url"] = MODEL_URL
    skill_dirs = config.setdefault("skills", {}).setdefault("external_dirs", [])
    if str(ROOT / "qsr-skills") not in skill_dirs:
        skill_dirs.append(str(ROOT / "qsr-skills"))

    servers = config.setdefault("mcp_servers", {})
    # Drop remote services whose ${VAR} URL expanded to empty (i.e. not configured).
    for name in list(servers):
        entry = servers[name]
        if isinstance(entry, dict) and "command" not in entry and not str(entry.get("url", "")).strip():
            del servers[name]

    python = str(ROOT / ".venv/mcp/bin/python")
    for script in sorted((ROOT / "tests/mcp-services").glob("*_server.py")):
        name = script.stem[: -len("_server")].replace("_", "-")
        servers[name] = {"command": python, "args": [str(script)], "enabled": True}
    enabled_names = [
        name for name, server in servers.items()
        if not isinstance(server, dict) or server.get("enabled", True)
    ]
    config.setdefault("platform_toolsets", {})["cli"] = sorted(enabled_names)

    temporary = HERMES_CONFIG.with_suffix(HERMES_CONFIG.suffix + ".tmp")
    temporary.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(HERMES_CONFIG)
    subprocess.run(["hermes", "config", "migrate"], check=True, stdin=subprocess.DEVNULL)
    subprocess.run(["hermes", "config", "check"], check=True, stdin=subprocess.DEVNULL)


def main() -> None:
    configure_hermes()
    os.execv(
        str(ROOT / ".venv/mcp/bin/python"),
        [str(ROOT / ".venv/mcp/bin/python"), "-u", str(ROOT / "operator-ui/app.py")],
    )


if __name__ == "__main__":
    main()