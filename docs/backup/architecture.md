# QSR Agent Architecture

[Repository overview](README.original.md) | [Documentation guide](index.md) |
[Setup](setup.md) | **Architecture** |
[Add a service](adding-a-service.md)

The deployable unit is one edge-hosted agent plus independently owned domain
services. The agent runtime may later change from Hermes to another MCP-capable
framework without moving source data or business policy into the agent.

## Responsibility Boundaries

| Component | Owns | Must not own |
|---|---|---|
| Agent runtime | Conversation, tool registration, skill loading, cross-domain orchestration | Restaurant source data or domain authorization |
| OVMS/Qwen | Reasoning, tool selection, answer synthesis | Tool execution or trusted state |
| MCP service | Domain reads, actions, validation, policy, audit data | Cross-domain conversation policy |
| Domain skill | Question routing, field interpretation, answer and action procedure | Live values, credentials, or enforceable authorization |
| `AGENTS.md` | Stable rules spanning every domain | Detailed per-service field mappings |

## Runtime Flow

```text
User
  -> Agent loads relevant domain skill
  -> Qwen selects a direct MCP tool
  -> Agent sends tools/call over local stdio or Streamable HTTP
  -> Domain service reads or acts through its policy gate
  -> Agent returns structured result to Qwen
  -> Qwen answers using only returned evidence
```

`tools.tool_search.enabled: off` is intentional while the catalog is small. It
gives Qwen the real MCP schemas directly and removes the deferred
`tool_search -> tool_describe -> tool_call` wrapper sequence.

## Hermes Runtime

The operator UI starts and supervises one always-on `hermes gateway run`
(API server on `127.0.0.1:8642`, fresh random keys each start) and restarts it
if it exits. Two Hermes profiles share it:

| Profile | Used for | Tools | Memory |
|---|---|---|---|
| default | Operator chat: one persistent conversation (**New chat** starts another) | MCP services, `memory`, `skills` (skill writes need approval) | Read and write |
| `qsr-events` | Event decisions | None | Read-only, injected into the prompt |

Hermes memory (`MEMORY.md`, `USER.md`) lives in `learning/hermes/memories` on
the `learning` volume, so operator preferences and context from chat survive
container recreation and inform event decisions. Hermes reviews chat into
memory every `QSR_MEMORY_NUDGE_INTERVAL` user turns (default 10). Event rules
are learnt separately by the [operator-taught learner](self-learning.md) and
applied in code.

Chat context is budgeted for the 64k-token window, cheapest step first:

1. After `QSR_CHAT_IDLE_MINUTES` (default 30) without a question, the next one
   starts a fresh conversation; memory carries over, so nothing is summarised.
2. Past `QSR_CHAT_PRUNE_TOKENS` (default 20000), Hermes drops bulky old tool
   results without a model call.
3. Past `QSR_CHAT_COMPRESS_TOKENS` (default 32000), Hermes summarises older
   turns and keeps the recent ones verbatim. That one turn takes about a minute
   longer on the local model; a turn adds only about 0.4k tokens, so this is
   rare.

The application never calls `hermes -z`: once a gateway runs, Hermes hands
one-shot turns to it with the full toolset, ignoring `--toolsets` and iteration
limits.

## Autonomy Event Flow

Event producers POST to the Operator UI `/autonomy/events` webhook. The UI
queues each event durably, Hermes selects skills and MCP reads, and any proposed
action waits for operator approval in the right-side Autonomy decisions panel.
See [Autonomous decisions](autonomy.md). Operator responses to events are
journaled and can be learnt into `learned-<service>` skills; see
[Operator-taught learning](self-learning.md).

## Repository Layout

```text
services/weather/                 Weather MCP service (simulator or Open-Meteo), events, Dockerfile
tests/mcp-services/
  service_base.py                 FastMCP service contract, policy gate, tool-call log
  service_launcher.py             Chooses one domain service per process
  kiosk_server.py                 Kiosk domain contract and implementation
  order_accuracy_server.py        Accuracy domain contract and implementation
  Dockerfile                      Simulation-only integration-test image
  hermes-mcp.example.yaml         Local test registration template
agent-config/hermes/
  config.example.yaml             Reusable Hermes runtime template
  remote-mcp.example.yaml         Remote MCP endpoint template
qsr-skills/
  kiosk-operations/SKILL.md       Kiosk routing and interpretation
  order-accuracy/SKILL.md         Accuracy routing and interpretation
autonomy/
  learning.py                     Learning journal, rule verification, learned-skill format
  learning_runner.py              Learner runs and Hermes skill approval (UI and CLI)
learning/
  simulated/                      Simulated operator history (deterministic)
  skills/learned-<service>/       Approved learned skills
scripts/setup.sh                   Local setup and verification
scripts/learn.py                   Learning CLI (import, status, run, approve)
docs/
  index.md                         Project entry point
  setup.md                         Complete local installation
  adding-a-service.md              Service-owner procedure
AGENTS.md                          Cross-domain orchestration rules
```

## Remote Deployment

Use Streamable HTTP for services running on separate machines. The Dockerfile
under `tests/mcp-services/` demonstrates this topology with simulated data; it
does not run Hermes and is not a production service image. Production services
should use authoritative handlers and sit behind HTTPS plus bearer-token or
mTLS enforcement. Restrict ingress to the agent machine.

The selected agent runtime owns only endpoint configuration. For Hermes:

```yaml
mcp_servers:
  service-name:
    url: https://service-name.example.internal/mcp
    transport: streamable-http
    headers:
      Authorization: Bearer ${SERVICE_MCP_TOKEN}
    enabled: true
```

The platform scope separately controls availability in ordinary sessions:

```yaml
platform_toolsets:
  cli:
    - kiosk
    - order-accuracy
```

Do not configure both `url` and `command` for the same server. Keep the working
stdio registration until the corresponding remote endpoint passes the agent's
MCP connectivity test, then replace it atomically.

Remote services that produce autonomy events need connectivity in both directions:

```text
QSR machine -> service-machine /mcp
service machine -> QSR-machine /autonomy/events
```

Use routable DNS names or IP addresses for separate machines. Put both endpoints
behind TLS and authentication in production, and restrict ingress to the known
service and agent hosts.

### Remote MCP TLS trust

For internal/demo HTTPS endpoints that use a self-signed certificate (for
example the digital-signage project's nginx proxy), `entrypoint.py`'s
`trust_remote_mcp_certs()` runs once at container startup: it fetches the
current certificate from every configured `https://` MCP server (trust on
first use, no out-of-band identity check) and writes a combined bundle
(system CAs plus these) to `~/.hermes/remote-mcp-ca-bundle.pem`, then points
`SSL_CERT_FILE` at it before Hermes starts. This keeps the container non-root
(no write access to the system CA store or `update-ca-certificates`) while
still letting Hermes verify these endpoints instead of failing outright.

Limitations:

- Only runs once per container start; a server that regenerates its cert on
  its own restarts (as digital-signage's nginx does) needs this container
  restarted too, to re-fetch and re-trust the new cert.
- A server unreachable at this container's startup is skipped silently (logged
  as a warning); use `make restart` (or a full recreate) once it is reachable.
- Only applies to processes started by the operator UI (including the Hermes
  gateway); ad-hoc `docker exec ... hermes` commands outside the gateway run
  with the container's static declared environment and do not see this trust
  bundle.
- TOFU is only reasonable on an internal/trusted network; production
  deployments should use a properly signed certificate instead.

## Service Owner Contract

Every service owner supplies these artifacts:

1. A stable MCP server name and HTTPS endpoint.
2. One broad `get_<domain>_context` read tool for general and complex questions.
3. Narrow action tools with typed inputs and policy gates.
4. JSON Schemas with units, time windows, confidence semantics, stable IDs,
   `schema_version`, `source`, and `observed_at` where applicable.
5. One domain `SKILL.md` containing question-to-tool-to-field mappings.
6. Tests for context shape, action denial/approval, and transport startup.
7. Health, audit, and tool-call logs that exclude credentials.

The broad context response should be bounded and decision-ready. Split it into
narrow reads only when payload size, latency, authorization, or update cadence
requires different handling.

## Adding a Service

Follow [adding-a-service.md](adding-a-service.md) for the complete server,
client, Hermes registration, skill, optional `AGENTS.md`, and test procedure.

## Verification Ladder

1. Unit-test the service function and policy gate without a model.
2. Start the service with `QSR_MCP_TRANSPORT=streamable-http`.
3. Run `hermes mcp test <service>` from the Hermes machine.
4. Ask one simple and one complex domain question.
5. Confirm the service observed `tools/call` and the answer matches its result.
6. Test a denied action and an approved action separately.
7. Test a cross-domain question with one service intentionally unavailable;
   Hermes must report partial coverage instead of fabricating the missing data.

---

[Previous: Complete setup](setup.md) |
[Next: Adding a service](adding-a-service.md)