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
hermes
```

Validate an existing installation without changing it:

```bash
./scripts/setup.sh --check
```

## Operator UI

A lightweight web UI lets an operator chat with the agent and see which services
are connected, without using the CLI. It has no extra dependencies (Python
standard library only) and drives the same Hermes agent under the hood.

`./scripts/setup.sh` starts it automatically at the end and prints the URL.
By default it binds on all interfaces so you can open it from another machine
on the LAN at `http://<host>:8600`. On the same host, use
`http://127.0.0.1:8600`. Set `START_UI=false` to skip the auto-start, or set
`QSR_UI_HOST=127.0.0.1` to restrict it to loopback.

To start it manually (or restart it later):

```bash
python3 operator-ui/app.py            # serves on http://<host>:8600
```

If you kept the default LAN binding, open `http://<host>:8600` from your
browser. If you set `QSR_UI_HOST=127.0.0.1`, forward the port first when the
agent is on a remote box:

```bash
ssh -L 8600:127.0.0.1:8600 <user>@<host>
```

The left panel lists connected MCP apps with live status and tool counts. The
center panel contains operator chat, while the right-side Automatic Alerts panel
shows subscribed critical events without inserting them into the conversation.
Ask questions like "List all suspicious-activity zones" or "What is our order
accuracy rate?" and the agent answers from live MCP services.

Options: `START_UI` (default `true`), `QSR_UI_HOST` (default `0.0.0.0`),
`QSR_UI_PORT` (default `8600`), and `QSR_MCP_SUBSCRIPTIONS` (JSON subscription
list). When started by setup, logs go to `/tmp/qsr-operator-ui.log`. See
[Automatic event subscriptions](docs/setup.md#automatic-event-subscriptions)
for same-machine Docker and distributed-machine examples.

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
