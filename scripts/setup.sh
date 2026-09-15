#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MODEL_ID=${MODEL_ID:-OpenVINO/Qwen3-8B-int4-ov}
MODEL_REVISION=${MODEL_REVISION:-5c47abf4b8e12ebe8e99745bb0c1ec17e0c0abcc}
MODEL_ROOT=${MODEL_ROOT:-"$HOME/models"}
OVMS_IMAGE=${OVMS_IMAGE:-openvino/model_server@sha256:2a52cd2bc62d984f35f12b1cf58bb5dffe5f5d57b6ef3349b1b37229a768806b}
OVMS_CONTAINER=${OVMS_CONTAINER:-ovms-qwen3-8b}
# Default off 8000 to avoid clashing with SAD's alert-service (make up binds :8000).
OVMS_PORT=${OVMS_PORT:-4444}
HERMES_CONFIG=${HERMES_CONFIG:-"$HOME/.hermes/config.yaml"}
HERMES_INSTALL_URL=${HERMES_INSTALL_URL:-https://hermes-agent.nousresearch.com/install.sh}
# The SDK is always installed from Git (no local-checkout dependency).
SDK_GIT_URL=${SDK_GIT_URL:-https://github.com/sachinkaushik/edge-ai-libraries.git}
SDK_GIT_REF=${SDK_GIT_REF:-mcp}
SDK_SUBDIR=${SDK_SUBDIR:-libraries/mcp-service-sdk}
SDK_INSTALL_DIR=""
# Optional: pin Hermes to a validated commit (full 40-char SHA). The installer
# tracks `main` by default, and newer builds have changed behavior (e.g. a
# >=64K context-window requirement). Set this to the SHA the stack was
# validated against to make installs reproducible for the customer handover.
HERMES_INSTALL_COMMIT=${HERMES_INSTALL_COMMIT:-}
SETUP_VENV=${SETUP_VENV:-"$ROOT_DIR/.venv/qsr-setup"}
SETUP_TARGET=${SETUP_TARGET:-"$ROOT_DIR/.venv/qsr-setup-target"}
# NOTE: we intentionally do NOT use `pip install git+...#subdirectory=...`. pip
# would run `git submodule update --init --recursive` and pull the entire
# edge-ai-libraries submodule tree (anomalib, flann, geti, ...), stalling setup.
# resolve_sdk_dir clones only the SDK subdirectory (sparse, no submodules).
# Dedicated venv whose interpreter launches the kiosk/order-accuracy MCP servers.
# Hermes runs those as subprocesses, so their launcher must have mcp-service-sdk.
MCP_VENV=${MCP_VENV:-"$ROOT_DIR/.venv/mcp"}
MCP_VENV_PY="$MCP_VENV/bin/python"
# Operator UI: started automatically at the end of setup. Set START_UI=false to
# skip, or override host/port.
START_UI=${START_UI:-true}
WARM_UP_UI=${WARM_UP_UI:-true}
# Bind on all interfaces by default so the UI is reachable from a browser on
# another machine without SSH port forwarding. Set QSR_UI_HOST=127.0.0.1 to
# restrict to loopback.
QSR_UI_HOST=${QSR_UI_HOST:-0.0.0.0}
QSR_UI_PORT=${QSR_UI_PORT:-8600}
# Registrations are convention-based, not per-service code: each QSR sim is a
# tests/mcp-services/<name>_server.py (auto-discovered), and real apps register
# themselves via their own launch. This script never changes to add a service.
SETUP_PYTHON=python3
SETUP_PYTHONPATH=
CHECK_ONLY=false

# Run completely unattended: never block on an interactive prompt. Standard
# "assume defaults" signals for the tools this script drives; unknown ones are
# harmless. Commands that might still try to read a TTY are invoked with stdin
# closed (< /dev/null) at their call sites.
export DEBIAN_FRONTEND=noninteractive
export CI=1
export HERMES_NONINTERACTIVE=1
export HERMES_NO_ANALYTICS=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1
export HF_HUB_DISABLE_TELEMETRY=1

# The model and MCP services are all on loopback. If a proxy is configured,
# localhost must bypass it or the OVMS call fails with "403 incorrect proxy
# service". Ensure loopback is always in no_proxy for setup-time calls.
export NO_PROXY="localhost,127.0.0.1,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"

usage() {
    cat <<'EOF'
Usage: scripts/setup.sh [--check]

Without arguments, install and configure the complete local QSR agent stack.
Use --check to validate an existing installation without changing it.

Optional environment variables:
    MODEL_ID            Hugging Face model ID
    MODEL_REVISION      Hugging Face commit revision
  MODEL_ROOT          Host model directory (default: $HOME/models)
    OVMS_IMAGE          OVMS GPU image reference
  OVMS_CONTAINER      OVMS container name
  OVMS_PORT           Loopback port for OVMS (default: 8000)
  HERMES_CONFIG       Hermes YAML path
  HERMES_INSTALL_URL  Hermes installer URL
    SETUP_VENV          Helper virtual environment path
    SETUP_TARGET        Fallback isolated dependency path
    SDK_GIT_URL         Git URL for mcp-service-sdk (default sachinkaushik fork)
    SDK_GIT_REF         Git ref/branch for mcp-service-sdk (default mcp)
    SDK_SUBDIR          Repo subdirectory holding the SDK
    MCP_VENV            Venv that launches the sim MCP servers
    START_UI            Auto-start the operator UI after setup (default true)
    WARM_UP_UI          Run one warm-up UI chat request during setup (default true)
    QSR_UI_HOST         Operator UI bind host (default 0.0.0.0)
    QSR_UI_PORT         Operator UI bind port (default 8600)
EOF
}

log() {
    printf '[qsr-setup] %s\n' "$*"
}

fail() {
    printf '[qsr-setup] ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing command '$1'. $2"
}

check_python_version() {
    python3 - <<'PY' || fail "Python 3.11 or newer is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

render_node() {
    local nodes=(/dev/dri/render*)
    [[ -e "${nodes[0]}" ]] || fail "No Intel render device found at /dev/dri/render*."
    printf '%s\n' "${nodes[0]}"
}

wait_for_ovms() {
    OVMS_URL="http://127.0.0.1:$OVMS_PORT/v3/models" MODEL_ID="$MODEL_ID" \
        python3 - <<'PY'
import json
import os
import time
import urllib.request

deadline = time.monotonic() + 300
url = os.environ["OVMS_URL"]
model_id = os.environ["MODEL_ID"]
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            models = json.load(response).get("data", [])
        if any(model.get("id") == model_id for model in models):
            raise SystemExit(0)
    except Exception:
        pass
    time.sleep(2)
raise SystemExit(f"OVMS did not make {model_id} available within 300 seconds")
PY
}

check_prerequisites() {
    [[ $(uname -s) == Linux ]] || fail "This setup targets Linux."
    require_command curl "Install curl and rerun setup."
    require_command docker "Install Docker Engine and rerun setup."
    require_command python3 "Install Python 3.11 or newer and python3-venv."
    require_command stat "Install GNU coreutils and rerun setup."
    check_python_version
    docker info >/dev/null 2>&1 || fail "Docker is not running or this user cannot access it."
    render_node >/dev/null
}

# Pre-install the packages the Hermes installer would otherwise apt-install via
# an interactive `sudo` mid-run. Installing them here (only when passwordless
# sudo is available) removes the sudo password pause during install, so the
# script never stalls before configure_hermes writes the provider config.
ensure_build_packages() {
    command -v apt-get >/dev/null 2>&1 || return 0
    local pkgs=(build-essential python3-dev libffi-dev ripgrep ffmpeg)
    local missing=()
    local p
    for p in "${pkgs[@]}"; do
        dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
    done
    [[ ${#missing[@]} -eq 0 ]] && return 0
    if sudo -n true 2>/dev/null; then
        log "Pre-installing build packages: ${missing[*]}"
        sudo -n env DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || true
        sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}" >/dev/null 2>&1 || true
    else
        log "NOTE: optional packages missing (${missing[*]}) and passwordless sudo unavailable."
        log "      The Hermes installer may prompt for a sudo password, or you can pre-install:"
        log "        sudo apt-get install -y ${missing[*]}"
    fi
}

ensure_helper_venv() {
    if PYTHONPATH="$SETUP_TARGET" python3 -c \
        'import huggingface_hub, yaml' >/dev/null 2>&1; then
        SETUP_PYTHON=python3
        SETUP_PYTHONPATH=$SETUP_TARGET
        log "Using isolated setup helpers at $SETUP_TARGET"
        return
    fi
    if [[ ! -x "$SETUP_VENV/bin/python" ]] ||
        ! "$SETUP_VENV/bin/python" -m pip --version >/dev/null 2>&1; then
        log "Creating setup virtual environment"
        if ! python3 -m venv "$SETUP_VENV" 2>/dev/null; then
            log "venv support unavailable; using isolated pip --target fallback"
            mkdir -p "$SETUP_TARGET"
            python3 -m pip install --quiet --upgrade --target "$SETUP_TARGET" \
                huggingface_hub PyYAML ||
                fail "Could not install setup helpers. Install python3-venv or pip."
            SETUP_PYTHON=python3
            SETUP_PYTHONPATH=$SETUP_TARGET
            return
        fi
    fi
    "$SETUP_VENV/bin/python" -m pip install --quiet --upgrade pip
    "$SETUP_VENV/bin/python" -m pip install --quiet --upgrade huggingface_hub PyYAML
    SETUP_PYTHON="$SETUP_VENV/bin/python"
}

ensure_test_sdk() {
    resolve_sdk_dir
    log "Installing mcp-service-sdk for local service tests from $SDK_INSTALL_DIR"
    if [[ -n $SETUP_PYTHONPATH ]]; then
        python3 -m pip install --quiet --upgrade --target "$SETUP_TARGET" "$SDK_INSTALL_DIR[mcp]"
    else
        "$SETUP_PYTHON" -m pip install --quiet --upgrade "$SDK_INSTALL_DIR[mcp]"
    fi
}

# Fetch the SDK from Git only, without submodules. Installing via pip's
# `git+...#subdirectory=...` runs `git submodule update --init --recursive`,
# which clones the whole edge-ai-libraries submodule tree and stalls setup. A
# shallow, sparse, no-submodule clone of just the SDK subdir is git-only and
# fast. Cached in SDK_INSTALL_DIR so we clone at most once per run.
resolve_sdk_dir() {
    [[ -n $SDK_INSTALL_DIR && -f "$SDK_INSTALL_DIR/pyproject.toml" ]] && return
    local dest
    dest=$(mktemp -d)
    log "Fetching mcp-service-sdk from $SDK_GIT_URL@$SDK_GIT_REF (sparse, no submodules)"
    git clone --depth 1 --filter=blob:none --sparse --no-recurse-submodules \
        --branch "$SDK_GIT_REF" "$SDK_GIT_URL" "$dest" >/dev/null 2>&1 ||
        fail "Could not clone mcp-service-sdk from $SDK_GIT_URL@$SDK_GIT_REF"
    git -C "$dest" sparse-checkout set "$SDK_SUBDIR" >/dev/null 2>&1 ||
        fail "Could not sparse-checkout $SDK_SUBDIR"
    [[ -f "$dest/$SDK_SUBDIR/pyproject.toml" ]] ||
        fail "Cloned SDK is missing pyproject.toml at $dest/$SDK_SUBDIR"
    SDK_INSTALL_DIR="$dest/$SDK_SUBDIR"
}

ensure_mcp_venv() {
    if [[ ! -x "$MCP_VENV_PY" ]]; then
        log "Creating MCP service venv at $MCP_VENV"
        python3 -m venv "$MCP_VENV" || fail "Could not create $MCP_VENV. Install python3-venv."
    fi
    "$MCP_VENV_PY" -m pip install --quiet --upgrade pip
    resolve_sdk_dir
    log "Installing mcp-service-sdk into the MCP service venv from $SDK_INSTALL_DIR"
    "$MCP_VENV_PY" -m pip install --quiet --upgrade "$SDK_INSTALL_DIR[mcp]" ||
        fail "Failed to install mcp-service-sdk into $MCP_VENV"
}

setup_python() {
    if [[ -n $SETUP_PYTHONPATH ]]; then
        PYTHONPATH="$SETUP_PYTHONPATH${PYTHONPATH:+:$PYTHONPATH}" "$SETUP_PYTHON" "$@"
    else
        "$SETUP_PYTHON" "$@"
    fi
}

install_hermes() {
    if ! command -v hermes >/dev/null 2>&1; then
        log "Installing Hermes Agent (unattended)"
        local installer
        installer=$(mktemp)
        curl -fsSL "$HERMES_INSTALL_URL" -o "$installer"
        # Official installer flags for zero-touch installs:
        #   --skip-setup       skip the interactive API-key/setup wizard
        #   --non-interactive  take defaults for every prompt (no gateway prompt)
        # Optionally pin to a validated commit for reproducible handover installs.
        # stdin is also closed so nothing can fall back to reading a TTY.
        local pin_args=()
        [[ -n "$HERMES_INSTALL_COMMIT" ]] && pin_args=(--commit "$HERMES_INSTALL_COMMIT")
        bash "$installer" --skip-setup --non-interactive "${pin_args[@]}" </dev/null
        rm -f "$installer"
        export PATH="$HOME/.local/bin:$PATH"
    fi
    require_command hermes "Add $HOME/.local/bin to PATH after installation."
    log "Using $(hermes --version | head -n 1)"
}

download_model() {
    local model_path="$MODEL_ROOT/$MODEL_ID"
    if [[ -f "$model_path/config.json" ]]; then
        log "Model already present at $model_path"
        return
    fi
    log "Downloading $MODEL_ID to $model_path"
    MODEL_ID="$MODEL_ID" MODEL_REVISION="$MODEL_REVISION" MODEL_ROOT="$MODEL_ROOT" \
        setup_python - <<'PY'
import os
from huggingface_hub import snapshot_download

model_id = os.environ["MODEL_ID"]
model_revision = os.environ["MODEL_REVISION"]
model_root = os.environ["MODEL_ROOT"]
print(snapshot_download(
    repo_id=model_id,
    revision=model_revision,
    local_dir=os.path.join(model_root, model_id),
))
PY
}

start_ovms() {
    local device group_id
    device=$(render_node)
    group_id=$(stat -c '%g' "$device")

    log "Pulling $OVMS_IMAGE"
    docker pull "$OVMS_IMAGE"
    if docker container inspect "$OVMS_CONTAINER" >/dev/null 2>&1; then
        log "Replacing existing $OVMS_CONTAINER container"
        docker rm -f "$OVMS_CONTAINER" >/dev/null
    fi

    log "Starting OVMS on http://127.0.0.1:$OVMS_PORT/v3"
    docker run -d --name "$OVMS_CONTAINER" --restart unless-stopped \
        --user "$(id -u):$(id -g)" \
        -p "127.0.0.1:$OVMS_PORT:8000" \
        -v "$MODEL_ROOT:/models" \
        --device /dev/dri \
        --group-add "$group_id" \
        "$OVMS_IMAGE" \
        --rest_port 8000 \
        --model_repository_path /models \
        --source_model "$MODEL_ID" \
        --target_device GPU \
        --tool_parser hermes3 \
        --task text_generation >/dev/null

    wait_for_ovms
}

# OpenVINO compiles the model on the first inference, not at load. Without this,
# the operator's first question after setup pays a 30-60s one-time compile.
# Sending one throwaway completion here moves that cost into setup instead.
warm_up_model() {
    log "Warming up the model (first-inference compile)"
    OVMS_URL="http://127.0.0.1:$OVMS_PORT/v3/chat/completions" MODEL_ID="$MODEL_ID" \
        python3 - <<'PY' || log "NOTE: model warm-up call did not complete; first query may be slow."
import json
import os
import urllib.request

url = os.environ["OVMS_URL"]
payload = json.dumps({
    "model": os.environ["MODEL_ID"],
    "messages": [{"role": "user", "content": "ready"}],
    "max_tokens": 1,
}).encode()
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=180) as response:
    response.read()
PY
}

configure_hermes() {
    local config_dir backup_path
    config_dir=$(dirname "$HERMES_CONFIG")
    mkdir -p "$config_dir"
    if [[ -f "$HERMES_CONFIG" ]]; then
        backup_path="$HERMES_CONFIG.bak.$(date -u +%Y%m%dT%H%M%SZ)"
        cp -p "$HERMES_CONFIG" "$backup_path"
        log "Backed up Hermes config to $backup_path"
    fi

    ROOT_DIR="$ROOT_DIR" HERMES_CONFIG="$HERMES_CONFIG" MODEL_ID="$MODEL_ID" \
        OVMS_PORT="$OVMS_PORT" \
        setup_python - <<'PY'
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

root = Path(os.environ["ROOT_DIR"])
config_path = Path(os.environ["HERMES_CONFIG"])
model_id = os.environ["MODEL_ID"]
ovms_base_url = f"http://127.0.0.1:{os.environ['OVMS_PORT']}/v3"
# Base config + remote/external service registrations (e.g. SAD). Local sims are
# auto-discovered below, so they are not listed in any fragment.
fragments = [
    root / "agent-config/hermes/config.example.yaml",
    root / "agent-config/hermes/remote-mcp.example.yaml",
]


def merge(current: Any, update: Any) -> Any:
    if isinstance(current, dict) and isinstance(update, dict):
        result = dict(current)
        for key, value in update.items():
            result[key] = merge(result[key], value) if key in result else value
        return result
    if isinstance(current, list) and isinstance(update, list):
        return current + [item for item in update if item not in current]
    return update


def replace_repo_path(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_repo_path(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_repo_path(item) for item in value]
    if isinstance(value, str):
        return value.replace("/absolute/path/to/qsr-agentic-svc", str(root))
    return value


current = {}
if config_path.exists():
    current = yaml.safe_load(config_path.read_text()) or {}
for fragment in fragments:
    current = merge(current, replace_repo_path(yaml.safe_load(fragment.read_text()) or {}))
current["model"]["default"] = model_id
current["model"]["provider"] = "custom"
current["model"]["base_url"] = ovms_base_url
current.setdefault("providers", {}).setdefault("custom", {})
current["providers"]["custom"]["base_url"] = ovms_base_url

# Auto-register the QSR-owned simulation services by convention: every
# tests/mcp-services/<name>_server.py becomes an MCP server launched by the SDK
# venv interpreter. Add a new sim by dropping a *_server.py — no edits here.
# Entries not managed here (e.g. real apps that self-register via their own
# `make up`) are preserved because we only touch discovered sim names.
servers = current.setdefault("mcp_servers", {})
venv_py = str(root / ".venv/mcp/bin/python")
for script in sorted((root / "tests/mcp-services").glob("*_server.py")):
    name = script.stem[: -len("_server")].replace("_", "-")
    servers[name] = {"command": venv_py, "args": [str(script)], "enabled": True}


# A remote MCP server (one with a `url`) is only enabled if its endpoint is
# reachable right now. This prevents a stopped/dead service (e.g. SAD not
# running) from costing an 8s connect-timeout on every agent turn. Local sims
# use `command` and are spawned on demand, so they are left enabled. Purely
# convention-based: no per-service code, and a service comes back online by
# rerunning setup (or re-enabling it) once its endpoint responds.
def _endpoint_alive(url: str, timeout: float = 2.0) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


for name, spec in servers.items():
    if isinstance(spec, dict) and spec.get("url"):
        alive = _endpoint_alive(str(spec["url"]))
        spec["enabled"] = alive
        print(f"[qsr-setup] remote MCP '{name}' {'reachable, enabled' if alive else 'unreachable, disabled'} ({spec['url']})")

# Derive the lean CLI toolset from the ENABLED services only (sims plus any
# reachable real apps), so Hermes' heavy default preset never bloats the prompt,
# new services are picked up automatically, and disabled/dead remotes are not
# referenced.
enabled_servers = [
    name for name, spec in servers.items()
    if not isinstance(spec, dict) or spec.get("enabled", True)
]
current.setdefault("platform_toolsets", {})["cli"] = sorted(enabled_servers)

temporary = config_path.with_suffix(config_path.suffix + ".tmp")
temporary.write_text(yaml.safe_dump(current, sort_keys=False))
temporary.chmod(0o600)
temporary.replace(config_path)
PY

    # Persist the loopback proxy bypass so the runtime `hermes` process reaches
    # OVMS on 127.0.0.1 even when a corporate proxy is set in the shell.
    local env_file
    env_file="$config_dir/.env"
    touch "$env_file"
    chmod 600 "$env_file"
    if ! grep -q '^NO_PROXY=' "$env_file" 2>/dev/null; then
        {
            echo "NO_PROXY=localhost,127.0.0.1,::1"
            echo "no_proxy=localhost,127.0.0.1,::1"
        } >> "$env_file"
    fi

    hermes config migrate >/dev/null </dev/null
    hermes config check </dev/null
}

wait_for_operator_ui() {
    local url="$1"
    local pid_file="$2"
    local attempt pid
    for attempt in {1..20}; do
        if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
            return 0
        fi
        pid=$(cat "$pid_file" 2>/dev/null || true)
        if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
            return 1
        fi
        sleep 1
    done
    return 1
}

start_operator_ui() {
    if [[ "${START_UI,,}" != "true" ]]; then
        log "START_UI=false; not starting the operator UI."
        return 0
    fi
    local ui="$ROOT_DIR/operator-ui/app.py"
    [[ -f "$ui" ]] || { log "Operator UI not found at $ui; skipping."; return 0; }
    local pid_file="/tmp/qsr-operator-ui.pid"
    local log_file="/tmp/qsr-operator-ui.log"
    # Probe over loopback even when binding on 0.0.0.0.
    local probe_host="$QSR_UI_HOST"
    [[ "$probe_host" == "0.0.0.0" ]] && probe_host="127.0.0.1"
    local url="http://$probe_host:$QSR_UI_PORT/health"
    local pid current_args
    pid=$(cat "$pid_file" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
            log "Operator UI already running (pid $pid, http://$QSR_UI_HOST:$QSR_UI_PORT)"
            return 0
        fi
        current_args=$(ps -p "$pid" -o args= 2>/dev/null || true)
        if [[ "$current_args" == *"$ui"* ]]; then
            log "Replacing unhealthy operator UI process (pid $pid)"
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        else
            fail "Refusing to reuse $pid_file because pid $pid is a different live process: $current_args"
        fi
    elif [[ -f "$pid_file" ]]; then
        rm -f "$pid_file"
    fi
    log "Starting operator UI on http://$QSR_UI_HOST:$QSR_UI_PORT"
    QSR_UI_HOST="$QSR_UI_HOST" QSR_UI_PORT="$QSR_UI_PORT" \
        nohup python3 -u "$ui" > "$log_file" 2>&1 &
    echo $! > "$pid_file"
    if ! wait_for_operator_ui "$url" "$pid_file"; then
        pid=$(cat "$pid_file" 2>/dev/null || true)
        if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$pid_file"
        fi
        tail -n 20 "$log_file" >&2 || true
        fail "Operator UI did not become ready on $url"
    fi
    log "Operator UI started (pid $(cat "$pid_file"), http://$QSR_UI_HOST:$QSR_UI_PORT, log: $log_file)"
}

operator_ui_probe_url() {
    local probe_host="$QSR_UI_HOST"
    [[ "$probe_host" == "0.0.0.0" ]] && probe_host="127.0.0.1"
    printf 'http://%s:%s' "$probe_host" "$QSR_UI_PORT"
}

warm_up_operator_ui() {
    if [[ "${START_UI,,}" != "true" || "${WARM_UP_UI,,}" != "true" ]]; then
        return 0
    fi
    local base_url
    base_url=$(operator_ui_probe_url)
    log "Warming up Hermes through the operator UI"
    curl -fsS --max-time 180 \
        -H 'Content-Type: application/json' \
        -d '{"question":"Reply with exactly: ready"}' \
        "$base_url/ask" >/dev/null ||
        log "NOTE: operator UI warm-up did not complete; first query may be slow."
}

validate_stack() {
    require_command hermes "Run scripts/setup.sh without --check to install Hermes."
    [[ -f "$MODEL_ROOT/$MODEL_ID/config.json" ]] ||
        fail "Model is missing from $MODEL_ROOT/$MODEL_ID."
    docker inspect -f '{{.State.Running}}' "$OVMS_CONTAINER" 2>/dev/null | grep -qx true ||
        fail "Container $OVMS_CONTAINER is not running."
    wait_for_ovms || fail "OVMS did not report $MODEL_ID as available."

    [[ -x "$MCP_VENV_PY" ]] || ensure_mcp_venv
    log "Running model-independent service tests"
    PYTHONDONTWRITEBYTECODE=1 "$MCP_VENV_PY" -m unittest discover \
        -s "$ROOT_DIR/tests/mcp-services" -p 'test_services.py' -v
}

main() {
    if [[ ${1:-} == --help || ${1:-} == -h ]]; then
        usage
        exit 0
    fi
    if [[ ${1:-} == --check ]]; then
        CHECK_ONLY=true
        shift
    fi
    [[ $# -eq 0 ]] || fail "Unknown argument: $1"

    check_prerequisites
    if [[ $CHECK_ONLY == false ]]; then
        ensure_build_packages
        ensure_helper_venv
        install_hermes
        download_model
        start_ovms
        warm_up_model
        ensure_mcp_venv
        configure_hermes
    fi
    validate_stack
    if [[ $CHECK_ONLY == false ]]; then
        start_operator_ui
        warm_up_operator_ui
    fi
    log "Setup is ready. Start the agent from this repository with: hermes"
    log "Operator UI: http://$QSR_UI_HOST:$QSR_UI_PORT  (START_UI=false to skip; WARM_UP_UI=false to skip warm-up; log: /tmp/qsr-operator-ui.log)"
}

main "$@"