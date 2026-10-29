# Configuration

## How Settings Are Applied

Edit `.env.example` in the repository root. Every `make up` copies it to `.env`,
so changes made directly to `.env` are overwritten.

| What you changed | Apply with |
|---|---|
| `.env.example` | `make up` |
| `agent-config/hermes/*.yaml` or `qsr-skills/` | `make restart` |

## Main Settings

| Variable | Default | Description |
|---|---|---|
| `MODEL_ROOT` | `./models` | Host directory that holds downloaded models |
| `MODEL_ID` | `OpenVINO/Qwen3-30B-A3B-Instruct-2507-int4-ov` | Model served by the OpenVINO™ Model Server. Use an OpenVINO™ model with tool-calling support, for example `OpenVINO/Qwen3-8B-int4-ov`. After changing it, run `make download-models` and `make up` |
| `QSR_UI_HOST` | `0.0.0.0` | Interface the operator UI listens on. Use `127.0.0.1` for local-only access |
| `QSR_UI_PORT` | `8600` | Operator UI port |
| `OVMS_PORT` | `4444` | Host port for the model server API (loopback only) |
| `WEATHER_PORT` | `8090` | Host port for the weather service (loopback only) |
| `HERMES_TIMEOUT` | `300` | Seconds to wait for one agent answer |
| `QSR_EXTRA_NO_PROXY` | empty | Comma-separated LAN hosts the agent must reach without the proxy |

## Image Source

| Variable | Default | Description |
|---|---|---|
| `REGISTRY` | `true` | `true` pulls the published image; `false` builds it locally |
| `REGISTRY_URL` | `intel/` | Registry and namespace prefix |
| `TAG` | `latest` | Image tag |

```bash
make up                                            # pull intel/qsr-agent:latest
make up REGISTRY_URL=myreg.io/team/ TAG=2026.2.0   # custom registry and tag
```

To build locally, see [Build from Source](build-from-source.md).

## Weather

By default the weather service is a simulator that you control with
`make weather`. To report live conditions for the store location instead, add
these lines to `.env.example`:

```bash
WEATHER_BACKEND=open-meteo
WEATHER_LATITUDE=12.97
WEATHER_LONGITUDE=77.59
WEATHER_LOCATION_NAME=My Restaurant
WEATHER_STORE_ID=qsr-001
```

Open-Meteo's free API is for non-commercial use. Commercial deployments need a
paid key or a self-hosted instance.

## Connect Store Services

Store systems connect to the agent as MCP services. They are listed in
`agent-config/hermes/remote-mcp.example.yaml`. Each entry needs a URL that the
agent container can reach:

```yaml
mcp_servers:
  your-service:
    url: https://your-service.example.internal/mcp
    transport: streamable-http
    enabled: true
    connect_timeout: 15
    timeout: 120
    headers:
      Authorization: Bearer ${YOUR_SERVICE_MCP_TOKEN}
```

- **Same machine:** use `host.docker.internal` instead of `127.0.0.1`. Inside
  the container, `127.0.0.1` refers to the container itself.
- **Another machine:** use its IP address or DNS name. If a proxy is set, add
  the host to `QSR_EXTRA_NO_PROXY`.
- **Disable a service:** set `enabled: false`.

The preconfigured entries read their URLs from `.env.example`. Leave
`QSR_SAD_MCP_URL` or `QSR_LP_MCP_URL` empty to skip that service:

| Service | Purpose | Setting |
|---|---|---|
| `weather` | Store-location weather | `QSR_WEATHER_MCP_URL` |
| `suspicious-activity` | Kitchen food-safety events | `QSR_SAD_MCP_URL` |
| `loss-prevention` | Self-checkout loss events | `QSR_LP_MCP_URL` |
| `digital-signage` | In-store advertising | `QSR_DIGITAL_SIGNAGE_MCP_URL` |
| `edgemart-sim-service` | Café-day orders, customers, and queue | `EDGEMART_SIM_MCP_URL` |
| `edgemart-table-sim-service` | Table occupancy and cleaning | `EDGEMART_TABLE_SIM_MCP_URL` |
| `edgemart-footfall-sim-service` | Zone footfall and busy hours | `EDGEMART_FOOTFALL_SIM_MCP_URL` |

Services that are not running appear as unavailable in **Connected apps**. The
agent keeps working with the services it can reach.

After editing the file, run `make restart`. Self-signed HTTPS certificates on
service endpoints are trusted automatically each time the agent starts. If a
service regenerates its certificate, restart the agent.

## Send Events From Store Systems

Store systems send events to the agent with an HTTP `POST` to
`http://<agent-host>:8600/autonomy/events`. See the
[API Reference](../api-reference.md#post-autonomyevents) for the event format.

## Proxy

Export proxy variables in the shell before `make up`. They are passed to image
builds and containers:

```bash
export http_proxy=http://proxy.example.com:8080
export https_proxy=$http_proxy
export no_proxy=localhost,127.0.0.1,::1
```

If your proxy intercepts TLS, configure the system or Docker daemon to trust
the organization's CA. Do not disable TLS verification.

## Secure Network Access

The operator UI has no built-in login. Anyone who can reach port 8600 can chat
with the agent and approve actions. For any deployment beyond a lab:

- Set `QSR_UI_HOST=127.0.0.1` and reach the UI through an SSH tunnel or an
  authenticating reverse proxy:

  ```bash
  ssh -L 8600:127.0.0.1:8600 user@agent-host
  ```

- Restrict port 8600 to the store network and the systems that send events.
- Use HTTPS and authentication (a bearer token or mTLS) on every remote store
  service.

---

[Back to Get Started](../get-started.md)
