# QSR Agentic Service

A reusable edge-agent architecture for quick-service restaurants. Hermes
orchestrates Q&A and actions, Qwen3-8B runs locally through OpenVINO Model
Server (OVMS) on Intel GPU, and MCP services retain ownership of restaurant
data, policy, actions, and audit evidence.

```text
Operator -> Hermes -> OVMS/Qwen -> MCP service -> domain system
         <- answer  <- tool use  <- typed result <- policy/audit
```

The included Kiosk and Order Accuracy services use simulated data. They prove
the integration contract and are not production restaurant systems.

## Quick Start

Prerequisites: Linux, Intel GPU access through `/dev/dri`, Python 3.11+, Docker,
Git, curl, and approximately 8 GB of free disk.

```bash
git clone https://github.com/intel-retail/qsr-agent.git
cd qsr-agent
./scripts/setup.sh
```

Setup starts the Operator UI automatically. Open:

```text
http://127.0.0.1:8600
```

The UI provides operator chat, connected-service status, and a right-side
Automatic Alerts panel for subscribed critical events. To use the CLI instead,
run `hermes` from the repository.

Validate an existing installation without changing it:

```bash
./scripts/setup.sh --check
```

## Uninstall

Tear down everything setup installed — Hermes, the OVMS container, and the
operator UI:

```bash
./scripts/uninstall.sh
```

Toggles:

- `REMOVE_OVMS=0` — keep the OVMS container.
- `KEEP_DATA=1` — keep `~/.hermes` (config and history).
- `KEEP_UV=1` — preserve bundled `uv`/`uvx`.

Model files under `~/models` and the local venvs (`.venv/`) are left in place.

## Documentation

| Document | Use it for |
|---|---|
| [Documentation guide](docs/index.md) | Reading order, repository map, and common tasks |
| [Complete setup](docs/setup.md) | Prerequisites, Hermes, OVMS, Docker, verification, and troubleshooting |
| [Architecture](docs/architecture.md) | Ownership, trust boundaries, transports, and deployment |
| [Adding a service](docs/adding-a-service.md) | MCP server/client, Hermes registration, skills, actions, and tests |

## Repository Map

| Path | Purpose |
|---|---|
| `mcp-service-sdk` Git dependency | Framework-neutral service contract, logging, policy, delivery, and MCP binding |
| `tests/mcp-services/` | Runnable Kiosk and Order Accuracy simulations |
| `qsr-skills/` | Hermes domain routing and interpretation procedures |
| `agent-config/hermes/` | Local and remote Hermes configuration fragments |
| `operator-ui/` | Standalone web chat UI + connected-services panel (stdlib only) |
| `scripts/setup.sh` | Idempotent local installation and validation |

## Current Scope

The local reference stack is tested with Hermes, OVMS, and
`OpenVINO/Qwen3-8B-int4-ov`. Production deployment still requires each service
owner to connect authoritative data, durable history, authenticated HTTPS MCP
endpoints, and real action handlers.
