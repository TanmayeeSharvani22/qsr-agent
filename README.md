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
make up
```

Every `make up` run copies `.env.example` to `.env`, replacing any existing
`.env`. Edit `.env.example` to configure remote services or other overrides.

`make up` starts the Hermes/operator image with OVMS through Docker Compose. By
default it **pulls** the pre-built image from the registry (`REGISTRY=true`); run
`make up REGISTRY=false` to **build from source**. Override the image reference
with `REGISTRY_URL` and `TAG` (default `intel/qsr-agent:latest`). The model must
already be present under `MODEL_ROOT/MODEL_ID`; the setup script can still be used
for the existing host-based installation. Open:

```text
http://127.0.0.1:8600
```

The UI provides operator chat, connected-service status, and a right-side
**Autonomy decisions** panel for event assessments and approvals. To use the CLI
instead, run `docker compose exec qsr-agent hermes`.

```bash
make logs
make status
make down
```

Register remote services in `agent-config/hermes/remote-mcp.example.yaml`, setting
each `url` to a routable MCP address, for example `http://10.0.0.25:9000/mcp`.

The UI also hosts a generic autonomy webhook. Hermes selects relevant skills
and MCP reads for incoming events; resulting actions wait for approval in the
**Autonomy decisions** panel. See
[Autonomous decisions](docs/autonomy.md) for runnable examples and extension
points.

There is no fixed event-to-action mapping. The included catalog supports menu
availability and order-remake proposals. Extensions add capabilities and skills,
not event policies. The application validates model-selected reads and proposed
actions, and records no-action reasons when intervention is not justified.

Weather comes from the weather MCP service in
[`services/weather`](services/weather/README.md), run as the compose `weather`
service. Set demo weather, which also sends a `weather_changed` event to the
autonomy webhook:

```bash
make weather CONDITION=rain TEMP=12        # clear|cloudy|fog|drizzle|rain|storm|snow
make weather CONDITION=clear NO_EVENT=1    # change silently
```

Behind a corporate proxy, export `http_proxy`, `https_proxy`, and `no_proxy`
before `make up`; they are passed to image builds and containers.

If you kept the default LAN binding, open `http://<host>:8600` from your
browser. If you set `QSR_UI_HOST=127.0.0.1`, forward the port first when the
agent is on a remote box:
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
| [Autonomous decisions](docs/autonomy.md) | Events, skill selection, capabilities, and approval |
| [Adding a service](docs/adding-a-service.md) | MCP server/client, Hermes registration, skills, actions, and tests |

## Repository Map

| Path | Purpose |
|---|---|
| `tests/mcp-services/` | Runnable Kiosk and Order Accuracy simulations on FastMCP, with a shared policy-gated service base |
| `qsr-skills/` | Hermes domain routing and interpretation procedures |
| `agent-config/hermes/` | Local and remote Hermes configuration fragments |
| `operator-ui/` | Web chat, connected services, and event decision approvals |
| `scripts/setup.sh` | Idempotent local installation and validation |

## Current Scope

The local reference stack is tested with Hermes, OVMS, and
`OpenVINO/Qwen3-8B-int4-ov`. Production deployment still requires each service
owner to connect authoritative data, durable history, authenticated HTTPS MCP
endpoints, and real action handlers.
