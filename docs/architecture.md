# QSR Agent Architecture

[Repository overview](../README.md) | [Documentation guide](index.md) |
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

## Event Subscription Flow

The operator UI is also a persistent MCP subscription client. This is separate
from Hermes, which is invoked per question for conversational reads and actions.
At UI startup, deployment configuration supplies a generic list of remote MCP
subscriptions. The UI calls each service's `subscribe` tool with an event type,
condition, and callback URL.

```text
QSR operator UI starts
  -> initialize remote MCP session
  -> call subscribe(event_type, condition, callback_url)

Domain service emits an event
  -> append the standard envelope to its durable log
  -> run normal delivery sinks
  -> match registered subscriptions
  -> POST the matching envelope to the callback URL
  -> QSR UI stores it in the notification queue
  -> QSR UI pushes it over Server-Sent Events (SSE)
  -> browser renders it immediately in the Automatic Alerts panel
```

The browser performs one `GET /notifications` when the page opens to restore
the backend's retained in-memory history. It then keeps a
`GET /notifications/stream` SSE connection open for new events; there is no
periodic alert polling.

For example, Suspicious Activity registers:

```text
event_type = report_suspicious_activity
condition = severity == critical
```

This path is deterministic and does not require an LLM decision. Hermes remains
available for follow-up investigation through the service's read tools.

Subscriptions are currently process-local. Restarting a domain MCP service
clears its registrations, so the operator UI must register again. Subscriptions
are forward-only: existing durable events are not replayed automatically.

## Repository Layout

```text
mcp-service-sdk (Git package)     Shared service contract and policy library
tests/mcp-services/
  service_runtime.py              Transport selection only
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
scripts/setup.sh                   Local setup and verification
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

Event subscriptions require connectivity in both directions:

```text
QSR machine -> service-machine /mcp
service machine -> QSR-machine /notifications
```

Use routable DNS names or IP addresses for separate machines. Put both endpoints
behind TLS and authentication in production, and restrict ingress to the known
service and agent hosts.

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