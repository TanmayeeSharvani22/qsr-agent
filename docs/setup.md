# Complete Local Setup

[Repository overview](../README.md) | [Documentation guide](index.md) |
**Setup** | [Architecture](architecture.md) |
[Add a service](adding-a-service.md)

This procedure reproduces the validated stack on a Linux x86-64 machine with
an Intel GPU. Hermes and the QSR simulations run on the host; OVMS runs in
Docker. The simulation Dockerfile is optional and runs MCP services only, not
Hermes.

## 1. Prerequisites

- Linux with an Intel GPU render node at `/dev/dri/renderD*`.
- Git, curl, and Python 3.11 or newer. The Python venv package is preferred.
- Docker Engine with permission to run containers as the current user.
- About 8 GB free disk for the model, image, and setup environment.
- Network access to GitHub, Docker Hub, PyPI, and Hugging Face.

On Ubuntu or Debian, install host tools and Docker as follows. Log out and back
in after adding the Docker group.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3 python3-venv
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sudo sh /tmp/get-docker.sh
sudo usermod -aG docker "$USER"
```

Then verify the two hardware/runtime requirements:

```bash
ls /dev/dri/renderD*
docker run --rm hello-world
```

Use the official Docker Engine instructions for non-Debian distributions. Do
not run the setup as root; the script writes Hermes state and models under the
current user's home directory.

### Proxy environments

The script honors standard proxy variables. Set these before setup when needed:

```bash
export HTTP_PROXY=http://proxy.example:port
export HTTPS_PROXY="$HTTP_PROXY"
export NO_PROXY=localhost,127.0.0.1,::1
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
export no_proxy="$NO_PROXY"
```

If TLS is intercepted, set `NODE_EXTRA_CA_CERTS` to the organization's trusted
PEM certificate. Configure the Docker daemon's proxy separately if `docker
pull` cannot reach Docker Hub. Do not disable TLS verification.

## 2. Run setup

```bash
git clone https://github.com/intel-retail/qsr-agent.git
cd qsr-agent
./scripts/setup.sh
```

The script is idempotent and performs these operations:

1. Validates Linux, Python, Docker, and `/dev/dri` access.
2. Installs Hermes with its official installer when `hermes` is absent.
3. Installs model/YAML helpers in `.venv/qsr-setup`; when venv support is
  unavailable, it uses an isolated `.venv/qsr-setup-target` directory.
4. Downloads `OpenVINO/Qwen3-8B-int4-ov` to `$HOME/models`.
5. Pulls the OVMS GPU image and starts `ovms-qwen3-8b` on loopback port 8000.
6. Backs up and merges `~/.hermes/config.yaml`; unrelated settings survive.
7. Registers Kiosk and Order Accuracy as local stdio MCP servers.
8. Validates OVMS, Hermes, MCP discovery, and service tests.

Validated artifact identities are pinned by default:

| Component | Identity |
|---|---|
| Hermes | v0.20.5 configuration schema 38 or a compatible newer install |
| Qwen model | `OpenVINO/Qwen3-8B-int4-ov` revision `5c47abf4b8e12ebe8e99745bb0c1ec17e0c0abcc` |
| OVMS GPU image | `sha256:2a52cd2bc62d984f35f12b1cf58bb5dffe5f5d57b6ef3349b1b37229a768806b` |

Useful overrides:

```bash
MODEL_ROOT=/data/models OVMS_PORT=8010 ./scripts/setup.sh
HERMES_CONFIG=/data/hermes/config.yaml ./scripts/setup.sh
```

Keep the same overrides when later running `./scripts/setup.sh --check`.

### Automatic event subscriptions

Edit `agent-config/hermes/subscribe-events.yaml` to configure proactive event
delivery to the Operator UI. Setup validates the enabled entries and loads them
automatically, so adding a service does not require changing
`operator-ui/app.py`.

For SAD and QSR running on the same machine, with SAD in Docker and QSR on the
host:

```yaml
subscriptions:
  - name: suspicious-activity-critical
    enabled: true
    url: http://127.0.0.1:9000/mcp
    event_type: report_suspicious_activity
    condition: severity == critical
    callback_url: http://host.docker.internal:8600/notifications
```

Then run `START_UI=true WARM_UP_UI=false ./scripts/setup.sh`.

Here, `url` is used by the host-based QSR UI to reach the published MCP port.
The callback originates inside the SAD container, so it uses
`host.docker.internal` to reach port 8600 on the Docker host. On Linux, the SAD
Compose service must include:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

For separate machines, use routable addresses instead:

```yaml
subscriptions:
  - name: suspicious-activity-critical
    enabled: true
    url: https://sad.example.internal/mcp
    event_type: report_suspicious_activity
    condition: severity == critical
    callback_url: https://qsr-agent.example.internal/notifications
```

Override `SUBSCRIBE_EVENTS_FILE` to use another YAML file. The
`QSR_MCP_SUBSCRIPTIONS` JSON environment variable remains available as a
higher-priority override for CI or generated deployments.

The domain service must expose the SDK `subscribe` contract and use an SDK
version that dispatches matching events after durable persistence. Restart the
operator UI after restarting a service so the process-local subscription is
registered again. Only events emitted after registration are pushed.

## 3. What Hermes receives

The setup merges [the reusable settings](../agent-config/hermes/config.example.yaml)
and [local test registrations](../tests/mcp-services/hermes-mcp.example.yaml).
The essential settings are:

```yaml
model:
  default: OpenVINO/Qwen3-8B-int4-ov
  provider: local-ovms
  base_url: http://127.0.0.1:8000/v3
  context_length: 65536
  max_tokens: 9000
providers:
  local-ovms:
    name: Local OVMS
    base_url: http://127.0.0.1:8000/v3
    default_model: OpenVINO/Qwen3-8B-int4-ov
    request_timeout_seconds: 1800
    stale_timeout_seconds: 1800
tools:
  tool_search:
    enabled: false
skills:
  external_dirs:
    - /absolute/path/to/qsr-agent/qsr-skills
```

`tool_search` is intentionally disabled while the MCP catalog is small. This
passes actual MCP schemas to Qwen and avoids the deferred
`tool_search -> tool_describe -> tool_call` wrapper that caused malformed calls.
The broad built-in-tool disable used during the earlier CPU/Ollama experiment
is not required for the final OVMS/Qwen3-8B setup. No Hermes source patch is
required.

Restart an interactive Hermes process after any configuration or skill change.

## 4. Exact OVMS bring-up

The setup script runs the equivalent of this validated command:

```bash
MODEL_ROOT="$HOME/models"
MODEL_ID=OpenVINO/Qwen3-8B-int4-ov
RENDER_NODE=$(find /dev/dri -maxdepth 1 -name 'renderD*' -print -quit)
RENDER_GROUP=$(stat -c '%g' "$RENDER_NODE")

docker rm -f ovms-qwen3-8b 2>/dev/null || true
docker run -d --name ovms-qwen3-8b --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  -p 127.0.0.1:8000:8000 \
  -v "$MODEL_ROOT:/models" \
  --device /dev/dri \
  --group-add "$RENDER_GROUP" \
  openvino/model_server@sha256:2a52cd2bc62d984f35f12b1cf58bb5dffe5f5d57b6ef3349b1b37229a768806b \
  --rest_port 8000 \
  --model_repository_path /models \
  --source_model "$MODEL_ID" \
  --target_device GPU \
  --tool_parser hermes3 \
  --task text_generation
```

`--tool_parser hermes3` is required for OpenAI-style tool calls. Confirm model
availability with:

```bash
curl -fsS http://127.0.0.1:8000/v3/models
docker logs ovms-qwen3-8b
```

## 5. Run and verify

Start Hermes from the repository so it reads the project `AGENTS.md`:

```bash
cd qsr-agent
hermes
```

Reproducible one-shot questions:

```bash
hermes -z 'What is the current restaurant queue count?' --cli
hermes -z 'What is the current order accuracy rate?' --cli
```

Independent checks:

```bash
./scripts/setup.sh --check
hermes mcp test kiosk
hermes mcp test order-accuracy
python3 tests/mcp-services/call_tool.py order-accuracy get_order_accuracy_context
```

The expected simulated accuracy is 87.5%: 21 accurate of 24 observed in a
30-minute window. A valid answer must come from an MCP call, not memory.

## 6. Optional containerized MCP services

This validates remote Streamable HTTP topology. It does not containerize
Hermes or OVMS:

```bash
docker build -f tests/mcp-services/Dockerfile -t qsr-mcp-service:local .
docker run --rm -p 127.0.0.1:8001:8000 \
  -e QSR_SERVICE=kiosk qsr-mcp-service:local
docker run --rm -p 127.0.0.1:8002:8000 \
  -e QSR_SERVICE=order-accuracy qsr-mcp-service:local
```

For production, put each `/mcp` endpoint behind HTTPS with bearer-token or
mTLS validation and restrict ingress to the agent host. Merge the shape in
`agent-config/hermes/remote-mcp.example.yaml` only after the endpoint passes
`hermes mcp test <name>`.

## Troubleshooting

| Symptom | Resolution |
|---|---|
| `hermes` not found after install | Run `export PATH="$HOME/.local/bin:$PATH"`, then open a new shell. |
| Model download fails in OVMS | Use the setup script; it downloads on the host and mounts the files. |
| OVMS cannot use GPU | Verify `/dev/dri/renderD*`, Docker permissions, and the render group passed to the container. |
| Config change appears ignored | Exit and restart the interactive Hermes process. |
| `-t order-accuracy` works but normal mode fails | Confirm `tools.tool_search.enabled` is `false` and the domain is in `platform_toolsets.cli`. |
| MCP is listed but answers are unsupported | Run `hermes mcp test`, then confirm the service observed `tools/call`. |
| `GET /mcp` returns 400 or 406 | The route exists; Streamable HTTP requires an initialized MCP session. |
| Automatic Alerts remains at `0` | Check `/tmp/qsr-operator-ui.log` for `Registered subscription`, verify the service exposes `subscribe`, confirm the callback is reachable from the service/container, and generate a new matching event after registration. |
| Same-host Docker callback fails | Use `host.docker.internal` plus the Linux `host-gateway` mapping; `127.0.0.1` inside a container refers to that container. |
| Alerts existed before UI startup but do not appear | Subscriptions are forward-only. Query durable history through MCP read tools or generate a new event after registration. |
| Python has no venv support | Setup automatically uses isolated `pip --target`; install `python3-venv` if the fallback is unavailable. |

---

[Previous: Documentation guide](index.md) |
[Next: Architecture](architecture.md)
