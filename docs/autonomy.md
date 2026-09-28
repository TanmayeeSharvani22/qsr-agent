# Autonomous Decisions

[Repository overview](../README.md) | [Documentation guide](index.md) |
[Architecture](architecture.md)

The generic event agent lets Hermes select skills and MCP reads from a trusted
capability catalog. Event names are not mapped to fixed actions:

```text
any webhook event -> Hermes selects skill(s) -> MCP reads -> decision
decision -> no-action explanation OR pending proposal -> approval -> MCP action
```

Hermes can choose `event-menu-decisions`, `kiosk-operations`, `order-accuracy`,
or extension skills, and read across services. Included actions are namespaced
`kiosk.change_menu_items` and `accuracy.request_remake`. Schema validation,
required live reads, owner validators, and approval constrain execution.
New event names need no registration; new domains need capabilities and skills.

## Included examples

### Weather event

Post weather changes to the operator server:

```bash
curl -sS -X POST http://127.0.0.1:8600/autonomy/events \
   -H 'Content-Type: application/json' \
   -d '{
      "event_id": "weather-demo-001",
      "event_type": "weather_changed",
      "store_id": "qsr-001",
      "occurred_at": "2026-09-21T12:00:00Z",
      "data": {
         "condition": "rain",
         "is_raining": true,
         "temperature_c": 14,
         "source": "weather-service"
      }
   }'
```

Hermes receives the weather event plus current queue, staffing, demand, and menu
state. It may recommend adding warm items such as `hot-chocolate` or `tea`,
restoring an item after weather clears, or making no change. Recommendations are
limited to exact live menu IDs and do not call `change_menu_items` until an
operator approves the proposal.

The operator UI displays the latest received weather event. It does not create
weather or run a polling loop. The event producer is responsible for detecting
weather changes, assigning unique event IDs, and retrying delivery failures.

### Queue event

Send a queue observation to the operator server:

```bash
curl -sS -X POST http://127.0.0.1:8600/autonomy/events \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "queue-demo-001",
    "event_type": "queue_count_changed",
    "store_id": "qsr-001",
    "occurred_at": "2026-09-18T12:00:00Z",
    "data": {"queue_count": 12}
  }'
```

Hermes receives the new queue count plus current wait time, staffing, recent
demand, weather, and menu state. It may temporarily hide preparation-intensive
items, restore them after recovery, or make no change. There is no hardcoded
queue threshold or fixed item selection. Duplicate `event_id` values are
ignored.

The application controls a bounded loop of structured Hermes responses, skill
loads, and MCP reads. It retains state between CLI calls; this is not unrestricted
native Hermes tool execution. The runner uses the working user provider config,
an empty working directory, and the `context_engine` toolset, verified to expose
zero tools in the installed Hermes build. Recheck isolation when upgrading.
Duplicate queued, processing, or successful events do not invoke Hermes again; failed evaluations
permit retry. At most five rounds and four reads per round are allowed.

An `order_mismatch_detected` event with an exact service-known `order_id` can
select accuracy guidance and propose a remake. Unknown or irrelevant events can
produce a no-action explanation. No event guarantees a proposal.

## Queued Event Processing

`POST /autonomy/events` validates the envelope, persists it in SQLite, and returns
HTTP 202 immediately without waiting for Hermes:

```json
{"ok":true,"event_id":"weather-demo-001","duplicate":false,"status":"queued"}
```

One background worker processes events in FIFO acceptance order. It completes
all skill-selection, context-read, and decision rounds for one event before
starting the next. Multiple producers can submit concurrently; no manual pause
between submissions is needed. The receipt is not a proposal or execution result.

`GET /autonomy/status` includes `queue.queued`, `queue.processing`, and decisions
with `queued`, `processing`, `pending`, `no_action`, or `failed` status. The UI
shows how many events are waiting and which events need approval. Technical
metadata and original JSON are available in collapsed details.

Queued events survive restart. An interrupted processing event is replayed
before later queued events; inference may therefore run more than once after a
crash. A failed event does not block later events and is not retried automatically;
resubmit the same ID to retry it at the end of the queue. A proposal's five-minute
expiry starts after evaluation, not when the event was queued.

Run one operator-server process per queue database. The worker is wake-driven,
not a source polling loop. Graceful shutdown finishes the active assessment and
leaves waiting events for restart. This queue serializes event inference only;
independent chat requests or other Hermes clients are not scheduled by it.

## Approval and execution

Open `http://127.0.0.1:8600`. The **Autonomy decisions** section shows selected
skills, reads, rationale, no-action outcomes, failures, and proposals. Each event
can propose one action; the menu action bundles at most three availability
changes. Approval rechecks permissions, schemas, fresh required context, and
owner validators. Proposals expire after five minutes. Reject makes no tool call.

The same workflow is available over HTTP:

```bash
curl -sS http://127.0.0.1:8600/autonomy/status
curl -sS -X POST \
  http://127.0.0.1:8600/autonomy/proposals/PROPOSAL_ID/approve \
  -H 'Content-Type: application/json' -d '{}'
```

The included kiosk action is a placeholder. An executed proposal proves the
policy, approval, MCP call, and audit path, but does not change a production
kiosk. Approved placeholder menu changes persist in
`~/.local/state/qsr-agent/kiosk-state.json`, so subsequent context calls reflect
the new availability or price. Set `QSR_KIOSK_STATE` to use another location.

## Placeholder Scenario Tests

Test each path with a known starting state, not just an accepted webhook. Use
the placeholder `change_menu_items` tool to prepare availability and record why
an item is hidden; subsequent context includes `availability_reason`. A hidden
item alone is not evidence that it can be restored after queue recovery.

- Rain: mark Tea and Hot Chocolate unavailable, then send rain at 14 C. Check
  Hermes's proposed changes, verify nothing changed while pending, approve in
  the UI, and read the menu again to verify the approved availability.
- Queue recovery: hide Vanilla Shake with a temporary queue-pressure reason.
  Start the operator server with `QSR_QUEUE_COUNT=0`,
  `QSR_ESTIMATED_WAIT_MINUTES=0`, and `QSR_WEATHER_CONDITION=clear`; send a queue
  event with `queue_count: 0` and `previous_queue_count: 20`. The service reason
  allows Hermes to choose the item without an item ID in the event. Reject a
  proposal and verify no state change; use a fresh event to test approval.
- Order mismatch: use the existing flagged ORD-1042 or ORD-1044 fixture. Verify
  the exact order's remake proposal in the UI and its approved placeholder
  result, or reject it and verify there is no execution result.

These are model-driven scenarios, not guaranteed mappings. Report no-action,
invalid-output, and timeout outcomes as such; do not inject a proposal to make
a test pass. Restore pre-test availability and remove temporary environment
overrides when done. Restart the operator server after changing its environment.
The original kiosk weather simulation alternates every 30 seconds and its
default queue is seven, so unconfigured snapshots can conflict with test events.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `QSR_AUTONOMY_DB` | `~/.local/state/qsr-agent/autonomy.db` | Durable decisions and deduplication |
| `QSR_RESTAURANT_ID` | `qsr-001` | Required service/store identity |
| `QSR_AUTONOMY_MODULES` | empty | Comma-separated extension modules |
| `QSR_AUTONOMY_DISABLED_TOOLS` | empty | Capabilities to remove at startup |
| `QSR_AUTONOMY_DISABLED_SKILLS` | empty | Skills to remove at startup |
| `HERMES_BIN` | `~/.local/bin/hermes` | Hermes executable |
| `QSR_ADVISOR_TIMEOUT` | `90` | Timeout per reasoning round, seconds |
| `QSR_ADVISOR_REASONING` | `none` | Hermes reasoning setting |
| `QSR_MCP_PYTHON` | `.venv/mcp/bin/python` | Local MCP interpreter |
| `QSR_KIOSK_SERVER` | kiosk placeholder path | Local kiosk MCP server |
| `QSR_ACCURACY_SERVER` | accuracy placeholder path | Local accuracy MCP server |
| `QSR_KIOSK_STATE` | `~/.local/state/qsr-agent/kiosk-state.json` | Persistent placeholder menu state |
| `QSR_QUEUE_COUNT` | `7` | Placeholder queue override, nonnegative integer |
| `QSR_ESTIMATED_WAIT_MINUTES` | `6` | Placeholder wait override, nonnegative integer minutes |
| `QSR_WEATHER_CONDITION` | alternating | Placeholder weather-condition override |

Model/provider settings come from the working user Hermes configuration.
The runner does not apply `QSR_ADVISOR_MODEL`, `QSR_ADVISOR_BASE_URL`, or
`QSR_ADVISOR_API_KEY` overrides to that configuration.

## Extending The Catalog

An extension's `register_autonomy(registry)` registers `Capability` objects in
`registry.catalog`, then `Skill` objects referencing them. Actions require read
dependencies and owner validators. Input schemas come from MCP discovery.
Registration is independent of event names. Removing a read also removes
dependent actions and referencing skills. Removing one skill does not disable
tools exposed by another skill. Restart after changing modules or disabled lists;
pending proposals with removed permissions fail closed on approval.

Event acceptance is asynchronous; a client disconnect does not cancel an accepted
event. SQLite supports queued-event recovery, but does not guarantee exactly-once
external actions. The HTTP server is a trusted-local demo without production
authentication or authorization. Add those controls, secure transport, delivery
recovery, and service-side idempotency before deployment.

Keep financial, safety-investigation, staffing, and irreversible actions behind
stronger service-owned approval gates. The controller approval is an operator
workflow, not a replacement for production authorization.