# Service-Owned Event Decisions

This standalone guide extends the generic agent without event-to-action policies.
Register capabilities and skills; Hermes selects relevant guidance, requests MCP
reads, and proposes an action or records a no-action reason. Writes require
operator approval. New event names need no registration.

## Contracts

An action service must expose a typed MCP tool and return structured content
containing `"executed": true` only when the action succeeded. Context tools must
return structured JSON objects. Keep authorization and operational safety gates
inside the owning service.

Register namespaced `Capability` objects in `registry.catalog`, then `Skill`
objects referencing them. Clients implement `list_tools()` and
`call_tool(name, arguments)`. Input schemas come from MCP discovery. Read results
must contain `restaurant.id` matching `QSR_RESTAURANT_ID` (default `qsr-001`).
Each action requires read dependencies and an owner validator. Every skill
exposing that action must include those reads. Skill text guides decisions;
catalog permissions, not event content or skill prose, authorize tools.

## Adding Another Event Skill

The event agent accepts all event names through its wildcard policy. Adding an
event such as `equipment_fault_detected` therefore does not require an
event-to-skill mapping. Add a domain only when Hermes needs new guidance, data,
or actions:

1. Expose typed read and action tools from the owning MCP service. Register each
    action with an appropriate service-side `GateLevel`; application approval is
    not a substitute for service authorization.
2. Register each tool as a namespaced `Capability`. Every action capability
    must declare its required read capabilities and a deterministic owner
    validator.
3. Create a `SKILL.md` describing relevant event types, required evidence,
    action bounds, and when no action is appropriate. A skill provides reasoning
    guidance and tool visibility, not authorization.
4. Register the `Skill` with all reads and actions it may use. Every required
    read for an action must be included in the same skill.
5. Send the new event to `POST /autonomy/events` and test both no-action and
    pending-proposal outcomes, approval, rejection, and a direct unauthorized
    MCP action call.

Hermes chooses the smallest relevant skill set at runtime and may combine
several skills and services for one event. It may request at most four reads in
one reasoning round. Each event produces at most one proposed action; expose a
service-owned atomic bundle action when several related writes must succeed
together. If an event only needs existing capabilities and guidance, no new
Python event policy is needed.

## Extension module

Create an importable Python module in the project, for example
`service_extensions/capacity_autonomy.py`. Export this function:

```python
from pathlib import Path

from autonomy.event_agent import Capability, Skill
from autonomy.mcp import StdioMcpClient
from autonomy.registry import AutonomyRegistry

from .validators import validate_notification


def register_autonomy(registry: AutonomyRegistry) -> None:
    client = StdioMcpClient(
        Path(".venv/mcp/bin/python"),
        Path("services/store_operations_server.py"),
    )
    registry.catalog.register_tool(Capability(
        "equipment.get_staff_context", "Read equipment faults and shift context",
        client, "get_staff_context", True,
    ))
    registry.catalog.register_tool(Capability(
        "equipment.notify_shift_lead", "Propose a fault notification",
        client, "notify_shift_lead", False,
        ("equipment.get_staff_context",), validate_notification,
    ))
    registry.catalog.register_skill(Skill(
        "equipment-response", "Assess equipment faults and notification needs",
        Path(__file__).with_name("SKILL.md"),
        ("equipment.get_staff_context", "equipment.notify_shift_lead"),
    ))
```

Enable one or more comma-separated modules before starting the operator UI:

```bash
export QSR_AUTONOMY_MODULES=service_extensions.capacity_autonomy
.venv/mcp/bin/python operator-ui/app.py
```

The built-in kiosk and accuracy registrations remain enabled. Duplicate names
and missing dependencies fail startup instead of replacing another owner.

## Owner Validation And Skills

Validators reject unsafe or unsupported arguments; they do not select actions.
They run before proposing and again against fresh required reads on approval.
Implement `validate_notification` for your service contract, for example:

```python
def validate_notification(arguments, observations):
    context = observations["equipment.get_staff_context"]
    equipment = context["equipment"]
    if arguments["equipment_id"] not in equipment:
        raise ValueError("unknown equipment")
    if equipment[arguments["equipment_id"]]["status"] != "fault":
        raise ValueError("equipment is no longer faulted")
```

This example assumes an `equipment` mapping keyed by ID. Add observation-age
checks, domain bounds, and cross-service time-window checks as appropriate.
Write trusted skill guidance describing relevance, evidence, action bounds, and
when no action is appropriate. Never include live operational values or secrets.
Hermes can select several skills and read across their services.

## Event Delivery

POST each observation with a globally unique `event_id`:

```bash
curl -sS -X POST http://127.0.0.1:8600/autonomy/events \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "fryer-2-health-20260921T120000Z",
    "event_type": "equipment_health_changed",
    "occurred_at": "2026-09-21T12:00:00Z",
    "data": {"equipment_id": "fryer-2", "severity": "critical"}
  }'
```

Invalid events are rejected and may be retried with the same ID. Valid duplicate
IDs are ignored. Event producers should retry network failures with the same ID.

Weather observations use the same generic endpoint:

```bash
curl -sS -X POST http://127.0.0.1:8600/autonomy/events \
    -H 'Content-Type: application/json' \
    -d '{
        "event_id": "weather-20260921T120000Z",
        "event_type": "weather_changed",
        "occurred_at": "2026-09-21T12:00:00Z",
        "data": {
            "condition": "rain",
            "is_raining": true,
            "temperature_c": 14,
            "source": "weather-service"
        }
    }'
```

The event producer owns change detection and delivery. The autonomy process has
no source polling loop. POST validates and durably queues the envelope, returning
HTTP 202 with `event_id`, `duplicate`, and `status: "queued"` before inference.
A single background worker evaluates accepted events in FIFO order, including
all Hermes rounds for an event before moving on. Concurrent submissions are safe
within the one server process; producers need not wait for a proposal.

Include `store_id` and `occurred_at` to provide identity and timing context.
Each event can propose one action; use a service-owned atomic bundle for related
changes. Unknown events can yield a no-action explanation. The UI and
`GET /autonomy/status` show selected skills, reads, rationale, and proposals.
Status also includes `queue.queued` and `queue.processing`, and decisions show
`queued` or `processing` while waiting or being assessed. Domain failures appear
as failed decisions after acceptance, not as webhook HTTP errors. Failed events
do not block the queue and may be explicitly retried with the same ID. Duplicate
queued, processing, or completed events do not create another job.
Approval rechecks permissions, a five-minute expiry, schemas, required context,
and the owner validator before calling the exact stored action. Rejection
makes no action call.

## Graceful Removal

Remove an extension module from `QSR_AUTONOMY_MODULES` and restart to remove its
capabilities. Individual exclusions are also supported:

```bash
export QSR_AUTONOMY_DISABLED_TOOLS=accuracy.request_remake
export QSR_AUTONOMY_DISABLED_SKILLS=event-menu-decisions
```

Extensions can call `catalog.remove_tools(*names)` and
`catalog.remove_skill(name)` during registration. Removing a read cascades to
dependent actions; removing a tool removes referencing skills. Removing one
skill does not disable tools exposed by another skill. Removal is idempotent.
These are startup APIs, not concurrent hot reload. Pending proposals whose
permissions were removed fail closed on approval.

## Verification checklist

1. Test skill selection, multiple reads, no-op, unsupported and malformed input.
2. Confirm the proposal is pending and the action service has not been called.
3. Approve it and verify the exact tool arguments and `executed` result.
4. Reject one and verify no action call occurs.
5. Send a duplicate event ID and verify no second proposal is created.
6. Restart the operator UI and verify durable proposal state in the configured
   `QSR_AUTONOMY_DB`.
7. Reject invalid schemas, mismatched identity, stale evidence, and expired or
    removed capabilities. Prove no write occurs during reasoning.
8. Block inference and prove POST still returns promptly, FIFO processing has
   one active event, and waiting/interrupted events recover after restart.

Run one operator-server process per queue database. SQLite persists waiting jobs;
interrupted processing jobs replay on startup, so inference is at-least-once
across crashes. Graceful shutdown finishes the current assessment and leaves
waiting work persisted. The queue does not guarantee exactly-once external actions
and does not serialize independent chat requests or other Hermes clients.
The bundled client is
stdio; other MCP transports need an adapter implementing the client interface.
The HTTP server is a trusted-local demo without production authentication or
authorization. Add those controls, secure transport, delivery recovery, and
service-side idempotency before production deployment.

Do not use this workflow for irreversible, financial, staffing, or safety
actions unless the owning service implements the required authorization and
approval gates. Controller approval is an operator workflow, not authorization.