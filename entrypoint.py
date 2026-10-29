#!/usr/bin/env python3
"""Initialize persistent Hermes configuration and launch the QSR operator UI."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


ROOT = Path("/opt/qsr")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
HERMES_CONFIG = Path(os.environ.get("HERMES_CONFIG", str(HERMES_HOME / "config.yaml")))
MODEL_ID = os.environ.get("MODEL_ID", "")
if not MODEL_ID:
    raise SystemExit("MODEL_ID is not set; set it in .env.example.")
MODEL_URL = os.environ.get("QSR_MODEL_BASE_URL", "http://ovms:8000/v3")
SYSTEM_CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")
REMOTE_MCP_CA_BUNDLE = HERMES_HOME / "remote-mcp-ca-bundle.pem"
# Hermes memories live on the learning volume so they survive container recreation
# (~/.hermes itself is baked into the image).
LEARNING_HOME = Path(os.environ.get("QSR_LEARNING_DIR", str(ROOT / "learning"))) / "hermes"
EVENTS_PROFILE = os.environ.get("QSR_HERMES_EVENTS_PROFILE", "qsr-events")


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


def _fetch_server_cert(host: str, port: int, timeout: float = 5.0) -> str | None:
    """Best-effort TOFU fetch of a remote MCP server's current TLS leaf cert (PEM).
    Returns None (logging why) rather than raising, so one unreachable/misconfigured
    service never blocks the whole container from starting."""
    try:
        return ssl.get_server_certificate((host, port), timeout=timeout)
    except (OSError, ssl.SSLError, socket.timeout) as exc:
        print(
            f"[entrypoint] Could not fetch TLS cert for {host}:{port} ({exc}); "
            "this MCP server may fail TLS verification if it uses a self-signed cert.",
            flush=True,
        )
        return None


def trust_remote_mcp_certs(servers: dict[str, Any]) -> None:
    """Best-effort trust-on-first-use for remote MCP servers using self-signed certs
    (e.g. digital-signage's nginx proxy, which regenerates its cert on every restart
    - this runs on every container start too, so it stays in sync with THIS
    container's restarts; it can still go stale if digital-signage's nginx
    restarts while this container keeps running).

    This container runs as a non-root user and cannot write to the system CA
    store or run update-ca-certificates, so instead of trusting system-wide we
    build our own bundle (system CAs + these fetched certs) and point Hermes's
    SSL_CERT_FILE at it - the Dockerfile already relies on that env var for
    Hermes's bundled Python to see any CA bundle at all.

    Security note: TOFU means a result is trusted without separately verifying
    identity out-of-band, so this is only reasonable on an internal/trusted
    network, same tradeoff this project already makes with self-signed certs
    elsewhere (e.g. nginx's own default cert).
    """
    fetched: list[str] = []
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url", ""))
        if not url.startswith("https://"):
            continue
        parsed = urlparse(url)
        if not parsed.hostname:
            continue
        cert = _fetch_server_cert(parsed.hostname, parsed.port or 443)
        if cert:
            fetched.append(cert)
            print(f"[entrypoint] Trusting current TLS cert for MCP server '{name}' "
                  f"({parsed.hostname}:{parsed.port or 443})", flush=True)

    if not fetched:
        return

    try:
        base = SYSTEM_CA_BUNDLE.read_text(encoding="utf-8") if SYSTEM_CA_BUNDLE.exists() else ""
        REMOTE_MCP_CA_BUNDLE.parent.mkdir(parents=True, exist_ok=True)
        REMOTE_MCP_CA_BUNDLE.write_text(base + "\n" + "\n".join(fetched), encoding="utf-8")
        REMOTE_MCP_CA_BUNDLE.chmod(0o600)
        os.environ["SSL_CERT_FILE"] = str(REMOTE_MCP_CA_BUNDLE)
    except OSError as exc:
        print(f"[entrypoint] Could not write combined CA bundle ({exc}); "
              "falling back to the system CA bundle only.", flush=True)


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

    trust_remote_mcp_certs(servers)

    python = str(ROOT / ".venv/mcp/bin/python")
    for script in sorted((ROOT / "tests/mcp-services").glob("*_server.py")):
        name = script.stem[: -len("_server")].replace("_", "-")
        servers[name] = {"command": python, "args": [str(script)], "enabled": True}
    enabled_names = [
        name for name, server in servers.items()
        if not isinstance(server, dict) or server.get("enabled", True)
    ]
    config.setdefault("platform_toolsets", {})["cli"] = sorted(enabled_names)
    # Operator chat runs on the always-on gateway: MCP services, Hermes memory, and the
    # skills tools so it can read QSR skills (skill writes need approval, see below).
    config["platform_toolsets"]["api_server"] = sorted(enabled_names) + ["memory", "skills"]
    config = _merge(config, _memory_settings())
    config["skills"].update({"creation_nudge_interval": 0, "write_approval": True})
    # Chat context budget on the 64k window: drop bulky old tool results without a model
    # call first, then summarise older turns once the conversation passes about half.
    config.setdefault("compression", {}).update({
        "proactive_prune_tokens": int(os.environ.get("QSR_CHAT_PRUNE_TOKENS", "20000")),
        "proactive_prune_min_result_chars": 2000,
        "threshold_tokens": int(os.environ.get("QSR_CHAT_COMPRESS_TOKENS", "32000")),
    })
    share_memories(HERMES_HOME)

    temporary = HERMES_CONFIG.with_suffix(HERMES_CONFIG.suffix + ".tmp")
    temporary.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(HERMES_CONFIG)
    subprocess.run(["hermes", "config", "migrate"], check=True, stdin=subprocess.DEVNULL)
    subprocess.run(["hermes", "config", "check"], check=True, stdin=subprocess.DEVNULL)
    configure_events_profile(config)


def _memory_settings() -> dict[str, Any]:
    return {"memory": {
        "memory_enabled": True,
        "user_profile_enabled": True,
        # User turns per chat session between background memory reviews.
        "nudge_interval": int(os.environ.get("QSR_MEMORY_NUDGE_INTERVAL", "10")),
    }}


def share_memories(home: Path) -> None:
    """Point a profile's memories/ at the persistent store shared by all QSR profiles."""
    target = LEARNING_HOME / "memories"
    target.mkdir(parents=True, exist_ok=True)
    link = home / "memories"
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return
        link.unlink()
    elif link.is_dir():
        for item in link.iterdir():
            if not (target / item.name).exists():
                shutil.move(str(item), str(target / item.name))
        shutil.rmtree(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)


def configure_events_profile(config: dict[str, Any]) -> None:
    """Event decisions: same model and read-only memory, but no tools at all, so Hermes
    can only recommend on untrusted events; actions still need operator approval."""
    home = HERMES_HOME / "profiles" / EVENTS_PROFILE
    if not (home / "config.yaml").is_file():
        subprocess.run(["hermes", "profile", "create", EVENTS_PROFILE, "--no-skills", "--no-alias"],
                       check=True, stdin=subprocess.DEVNULL)
    profile = _load_yaml(home / "config.yaml")
    for key in ("model", "providers", "custom_providers", "tools"):
        if key in config:
            profile[key] = config[key]
    profile = _merge(profile, _memory_settings())
    profile["mcp_servers"] = {}
    # Toolset without tools: memory notes are still injected into the prompt, but untrusted
    # event data can never write them.
    profile["platform_toolsets"] = {"api_server": ["context_engine"]}
    profile.setdefault("agent", {}).update({
        "max_turns": 1,
        "reasoning_effort": os.environ.get("QSR_ADVISOR_REASONING", "none"),
    })
    path = home / "config.yaml"
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    path.chmod(0o600)
    share_memories(home)

    # Fresh per start: the multiplexed gateway authenticates /p/<profile>/ with this key.
    env_path = home / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
    lines = [line for line in lines if not line.startswith("API_SERVER_KEY=")]
    lines.append(f"API_SERVER_KEY={secrets.token_urlsafe(32)}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_path.chmod(0o600)


def main() -> None:
    configure_hermes()
    # Explicit env (not execv's implicit current-environ) so SSL_CERT_FILE always propagates.
    os.execve(
        str(ROOT / ".venv/mcp/bin/python"),
        [str(ROOT / ".venv/mcp/bin/python"), "-u", str(ROOT / "operator-ui/app.py")],
        dict(os.environ),
    )


if __name__ == "__main__":
    main()