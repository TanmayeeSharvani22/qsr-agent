# Weather MCP Service

Part of the QSR agent. A weather MCP service for demos: you decide the weather
(rain, clear, storm, snow, any temperature) and the service reports it as if it
were real. For a real deployment, switch it to live weather from Open-Meteo by
changing one environment variable; agents and skills stay the same.

The QSR stack runs it for you: `make up` builds this directory as the compose
`weather` service, and `scripts/setup.sh` installs it into `.venv/mcp` and
starts it on the host. Hermes registers it as the `weather` MCP server, and
autonomy reads it through `QSR_WEATHER_MCP_URL`.

## Why A Simulator?

No existing open-source weather MCP server lets you choose conditions on demand.
The closest real-data option is
[`isdaniel/mcp_weather_server`](https://github.com/isdaniel/mcp_weather_server)
(Apache-2.0, no API key, backed by [Open-Meteo](https://open-meteo.com/)). It
returns live weather only, and Open-Meteo's free hosted API is limited to
non-commercial use (CC-BY 4.0, under 10,000 calls a day). Commercial use needs
a paid key or a self-hosted Open-Meteo instance.

This service therefore matches that server's tool names, inputs, and fields:

| Tool | Input | Output |
|---|---|---|
| `get_current_weather` | `city` (optional) | Human-readable summary |
| `get_weather_details` | `city` (optional) | Structured JSON record |

Without `city`, the configured store location is used. Each record contains
the `mcp_weather_server` fields (`temperature_c`, `weather_code`, `rain_mm`,
`wind_speed_kmh`, ...) plus `condition`, `is_raining`, `source`, `simulated`,
and `observed_at`.

## Quick Start

Built on [FastMCP](https://gofastmcp.com) 4.x (Python 3.11+). To run it on its
own, from this directory:

```bash
python3 -m venv .venv && .venv/bin/pip install -e .

.venv/bin/weather-simulator set rain --temperature 12   # make it rain
.venv/bin/weather-simulator show                        # inspect current weather
.venv/bin/weather-simulator set clear --temperature 24  # clear it up
.venv/bin/weather-simulator reset                       # back to the default
```

Conditions: `clear`, `cloudy`, `fog`, `drizzle`, `rain`, `storm`, `snow`.
Temperatures from -60 to 60 °C are accepted. The weather is saved in
`WEATHER_SIM_STATE`, so the CLI and every server process see the same value.

Run the MCP server:

```bash
.venv/bin/weather-simulator                     # stdio (default)
.venv/bin/weather-simulator serve --transport http --port 8090
```

`--transport http` serves MCP Streamable HTTP at `/mcp`; `streamable-http` is
accepted as an alias and `sse` serves the legacy SSE transport. In HTTP mode
the server also provides:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness check and active backend |
| `GET /simulator/weather` | Current simulated weather |
| `POST /simulator/weather` | `{"condition": "rain", "temperature_c": 12, "publish_event": true}` |
| `POST /simulator/weather/reset` | Restore the default weather |

```bash
curl -X POST http://127.0.0.1:8090/simulator/weather \
  -H 'Content-Type: application/json' -d '{"condition":"rain","temperature_c":12}'
```

## Docker

With the QSR stack, `make up` builds and runs this image as the `weather`
service; change demo weather from the repository root with
`make weather CONDITION=rain TEMP=12`. To run it standalone:

```bash
docker build -t qsr-weather:local .
docker run -d --name weather -p 127.0.0.1:8090:8090 \
  -e WEATHER_EVENT_WEBHOOK_URL=http://qsr-agent:8600/autonomy/events \
  -v weather-state:/home/weather/.local/state/weather-simulator \
  qsr-weather:local
docker exec weather weather-simulator set rain --temperature 12
```

The container binds `0.0.0.0:8090` and stores weather in the mounted volume.
Requests through a published port do not come from loopback, so
`/simulator/*` returns 403 unless `WEATHER_SIM_CONTROL_TOKEN` is set; use
`docker exec ... weather-simulator set` instead. Behind a proxy, pass
`--build-arg http_proxy=... --build-arg https_proxy=...` to the build and add
the webhook host to `no_proxy` at runtime.

## Triggering QSR Events

When the weather changes, the service can POST a `weather_changed` event to
the QSR agent, which then evaluates it like any other weather event:

```bash
export WEATHER_EVENT_WEBHOOK_URL=http://127.0.0.1:8600/autonomy/events
export WEATHER_STORE_ID=qsr-001
.venv/bin/weather-simulator set rain --temperature 12
```

The event looks like this:

```json
{
  "event_id": "weather-qsr-001-20261005T120000Z-1a2b3c4d",
  "event_type": "weather_changed",
  "store_id": "qsr-001",
  "occurred_at": "2026-10-05T12:00:00+00:00",
  "data": {
    "condition": "rain", "is_raining": true, "temperature_c": 12.0,
    "weather_code": 63, "weather_description": "Moderate rain",
    "precipitation_mm": 3.2, "location": "Demo Store",
    "source": "weather-simulator", "simulated": true,
    "previous": {"condition": "clear", "is_raining": false, "temperature_c": 22.0}
  }
}
```

An event is sent only when the condition or rain state changes, or the
temperature moves by at least `WEATHER_EVENT_TEMPERATURE_DELTA_C`. Use
`--no-event` (or `"publish_event": false`) to stage weather silently before a
demo. Failed deliveries are retried twice with backoff; most 4xx responses are
not retried.

The QSR agent registers the server with Hermes through
`agent-config/hermes/remote-mcp.example.yaml` (`url: ${QSR_WEATHER_MCP_URL}`,
`transport: streamable-http`). To register a stdio instance manually instead:

```yaml
mcp_servers:
  weather:
    command: /absolute/path/to/qsr-agent/.venv/mcp/bin/weather-simulator
    env:
      WEATHER_LOCATION_NAME: Demo Store
    enabled: true
```

## Switching To Real Weather

**Option A: this service with the Open-Meteo backend.** The tools and event
publishing stay the same; only the data source changes.

```bash
export WEATHER_BACKEND=open-meteo
export WEATHER_LATITUDE=37.39 WEATHER_LONGITUDE=-121.96 WEATHER_LOCATION_NAME="Store 001"
# Commercial use: a paid key, or a self-hosted Open-Meteo instance:
# export OPEN_METEO_API_KEY=...
# export OPEN_METEO_BASE_URL=https://customer-api.open-meteo.com/v1/forecast
# export OPEN_METEO_BASE_URL=http://open-meteo.internal:8080/v1/forecast
.venv/bin/weather-simulator serve --transport http --port 8090
```

Live weather does not push changes, so run a poller to produce events:

```bash
.venv/bin/weather-simulator watch --interval 600
```

The first poll sets a baseline; later polls publish significant changes. The
minimum interval is 60 seconds, to stay within free-tier rate limits. Control
tools and `/simulator/*` routes are disabled with this backend.

**Option B: replace this service with `mcp_weather_server`.** Point the Hermes
`weather` entry at `python -m mcp_weather_server`. Its tools require `city`,
and it publishes no events, so keep a separate event producer.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `WEATHER_BACKEND` | `simulator` | `simulator` or `open-meteo` |
| `WEATHER_LOCATION_NAME` | `Demo Store` | Location used when `city` is omitted |
| `WEATHER_LATITUDE` / `WEATHER_LONGITUDE` | unset | Store coordinates; required for Open-Meteo without `city` |
| `WEATHER_SIM_STATE` | `~/.local/state/weather-simulator/state.json` | Shared simulator state |
| `WEATHER_SIM_DEFAULT_CONDITION` | `clear` | Weather before the first change and after `reset` |
| `WEATHER_SIM_DEFAULT_TEMPERATURE_C` | per-condition | Default temperature override |
| `WEATHER_SIM_CONTROL_TOKEN` | unset | Bearer token for `/simulator/*`; without it, only loopback clients are allowed |
| `WEATHER_SIM_EXPOSE_CONTROL_TOOLS` | `false` | Also expose `set_simulated_weather` / `reset_simulated_weather` as MCP tools |
| `WEATHER_EVENT_WEBHOOK_URL` | unset | Where `weather_changed` events are sent |
| `WEATHER_EVENT_WEBHOOK_TOKEN` | unset | Optional bearer token for the webhook |
| `WEATHER_STORE_ID` | `qsr-001` | `store_id` in events |
| `WEATHER_EVENT_TEMPERATURE_DELTA_C` | `1.0` | Minimum temperature change that triggers an event |
| `OPEN_METEO_BASE_URL` | hosted forecast API | Forecast endpoint (hosted, paid, or self-hosted) |
| `OPEN_METEO_GEOCODING_URL` | hosted geocoding API | City lookup endpoint |
| `OPEN_METEO_API_KEY` | unset | Paid Open-Meteo key |

## Notes

- Control tools are off by default so an agent cannot change the weather it is
  reasoning about. Enable them only for scripted demos.
- When binding HTTP to a non-loopback address, set
  `WEATHER_SIM_CONTROL_TOKEN` and put TLS/authentication in front of `/mcp`.
- Webhook delivery and HTTP MCP clients honor `http_proxy`/`no_proxy`. Behind
  a corporate proxy, add `127.0.0.1,localhost` and the QSR/service hosts to
  `no_proxy`, or clients fail with an MCP error response from the proxy.
- Over stdio, the server cancels in-flight requests when the client closes
  stdin immediately after sending. Persistent clients such as Hermes are
  unaffected; one-shot clients should use HTTP or keep stdin open until the
  response arrives.

## Tests

From the QSR repository root, using the MCP venv created by `scripts/setup.sh`:

```bash
.venv/mcp/bin/python -m unittest discover -s services/weather/tests -v
```

Tests make no network calls; the Open-Meteo provider and webhook are stubbed.
