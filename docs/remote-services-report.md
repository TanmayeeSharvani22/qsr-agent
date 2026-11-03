# Kiosk and Order Accuracy on Remote Hosts: Coverage and Test Report

Date: 2026-11-02. Branch `selflearn-all-services` (qsr-agent), uncommitted changes in
`smart-kiosk-assistant` and `order-accuracy` (take-away, dine-in).

## Summary

The kiosk and both Order Accuracy services now provide the MCP tools the agent's
built-in `kiosk` and `accuracy` capabilities use, and push their events to the agent.
With the remote URLs set, the agent uses only the remote services: no local kiosk or
order-accuracy simulation runs. Chat, event decisions, approvals, and the learning
journal all work against the real service code.

| Service | Reads | Actions | Events pushed to the agent |
|---|---|---|---|
| Kiosk (smart-kiosk-assistant, MCP :8014) | `get_kiosk_context` (new), `get_queue_depth`, `get_queue_history`, `get_order_stats`, `get_board_state`, `get_menu_requests`, `describe` | `change_menu_items` (new), `update_kiosk_settings` (new), `update_menu_item`, `add_menu_item`, `set_board_mode` | `queue_count_changed` with `service: kiosk`, `queue_count`, `previous_queue_count`, `estimated_wait_minutes` |
| Order Accuracy take-away (MCP :8010) | `get_order_accuracy_context` (new), `get_rework_rate`, `get_order_history`, `get_station_totals`, `describe` | `request_remake` (new) | `order_mismatch_detected` (and `order_validated`) with `service: accuracy`, `venue: take-away` |
| Order Accuracy dine-in (MCP :8011) | same as take-away | `request_remake` (new) | same, `venue: dine-in` |

Every action the agent proposes runs only after an operator approves it. Each service
also validates the action itself.

## Questions and Answers

Status: **Live** = run against the running stack (real service code, real model);
**Unit** = covered by automated tests; **Supported** = tool exists and is documented,
not exercised in a test here.

### Kiosk

| Operator question or event | What the agent uses | Status | Observed result |
|---|---|---|---|
| "How long is the kiosk queue right now and which kiosk mode are we in?" | `get_kiosk_context` | Live | "The kiosk queue has 2 customers (status: LOW), and the kiosk is currently in full board mode." After the change below: "14 customers ... simplified board mode with upsell disabled and four kiosks active." |
| What is the estimated wait? | `get_kiosk_context.operations.estimated_wait_minutes` (queue × minutes per order ÷ active kiosks) | Live, Unit | Wait 10 min at queue 14 with 3 kiosks, 7 min after switching to 4 |
| Which menu items are available? | `get_kiosk_context.menu.items` (catalogue, `id` = product id) | Unit | Items listed with `available` |
| Orders in the last 15 minutes, top item | `get_kiosk_context.recent_activity` | Unit | |
| Is the queue always deep at this time? | `get_queue_history` | Supported | Existing kiosk tool |
| Confirmed orders, revenue, top items today | `get_order_stats` | Supported | Existing kiosk tool |
| Pending menu changes awaiting approval | `get_menu_requests` | Supported | Existing kiosk tool |
| Event: queue rises to 14 | `queue_count_changed` → agent reads context → proposal | Live | Proposal `update_kiosk_settings {mode: express, active_kiosks: 4, upsell_enabled: false}` from skills `learned-kiosk`, `kiosk-operations`. Approved → executed on the remote kiosk: board `simplified`, upsell off, 4 kiosks |
| "Turn tea off / hot chocolate on" | `change_menu_items` (through the kiosk's `update_menu_item` gate) | Unit | Bundle applied; unknown, duplicate, or already-set items rejected |
| "Switch to express / turn upsell off / open a kiosk" | `update_kiosk_settings` | Live, Unit | Express sets the board to `simplified`; upsell off makes the ordering upsell engine return no suggestions; `active_kiosks` limited to 1..`max_kiosks` |

### Order Accuracy (take-away and dine-in)

| Operator question or event | What the agent uses | Status | Observed result |
|---|---|---|---|
| Which orders are flagged right now, and why? | `get_order_accuracy_context` (recent orders with `result` and `issues`) | Live, Unit | Flagged take-away and dine-in orders listed with missing/extra/quantity issues; seeded baseline history excluded |
| Accuracy over the last 30 minutes, per station | `get_order_accuracy_context.summary`, `.stations` | Unit | Take-away and dine-in merged into one `accuracy` view when both are connected |
| Rework rate today vs. yesterday | `get_rework_rate` | Supported | Existing tool |
| Order history, per-station totals | `get_order_history`, `get_station_totals` | Supported | Existing tools; remake requests do not appear as validation outcomes (Unit) |
| Event: a take-away order fails validation | `order_mismatch_detected` → agent reads context | Live | `no_action`: the base skill leaves remakes to the operator until a learned accuracy skill exists |
| "Remake order LIVE-11758, the fries were missing." (in chat, event shown) | `request_remake` on the venue in `data.venue` | Live | "Order LIVE-11758 has been successfully remade." Take-away recorded `remake_requested_at`; journal recorded `accuracy.request_remake`. Passed twice in a row |
| Remake a dine-in order | `request_remake` on dine-in | Unit | Not run live; dine-in flagged orders confirmed in its context live |
| Remake an order that is not flagged, or on the wrong venue | `request_remake` | Unit | Rejected; the error names the other venue's service |
| Comp or dismiss an alert | none | Not supported | The skill tells the agent to say so |

### Extras (same branch)

| Question or event | Status | Observed result |
|---|---|---|
| Plug-and-play: a new MCP service (table sim) with no agent code. "Mark table-4 as cleared." | Live | "Table-4 has been marked as cleared." Journaled as `table-occupancy-service.mark_table_cleared {table_id: table-4}` |
| A service reports an operator response itself (`POST /learning/responses`) | Live, Unit | 201 recorded; same `response_id` again adds nothing; a read tool or unknown tool returns 400 |
| Weather (`weather_changed`) and learning across kiosk, weather, accuracy | Live (learner), Unit | Learner on Qwen3-30B: kiosk 7 rules in 61 s, weather 3 rules in 40 s, accuracy 1 rule in 26 s (remake with the order id taken from the event) |
| Chat actions journaled from Hermes's own tool calls (no server logs needed) | Live, Unit | Recorded with the MCP server logs deleted |

## Self-Learning: Events and Responses Tested

All services write to one learning journal. Each record holds the event (with its
service), the live context the agent read, what the agent proposed, and what the
operator did. The learner turns these records into rules, checks every rule against
the records, and an operator approves the resulting skill.

### Responses captured into the journal

| Source | Event | Operator response | Recorded as | Status |
|---|---|---|---|---|
| Chat while the event is shown | `queue_count_changed` (queue 12, wait 9) | "Switch kiosks to express, open kiosk 4 and turn upsell off." | `instruction`, `kiosk.update_kiosk_settings` with the arguments Hermes used; captured from Hermes's stream with the MCP server logs deleted | Live |
| Chat while the event is shown | `order_mismatch_detected` (take-away, remote) | "Remake order LIVE-11758, the fries were missing." | `instruction`, `accuracy.request_remake {order_id: LIVE-11758, ...}` | Live |
| Chat while the event is shown | `table_dirty` (table sim, no agent code) | "Mark table-4 as cleared." | `instruction`, `table-occupancy-service.mark_table_cleared {table_id: table-4}` | Live |
| Approve in the console | `queue_count_changed` (queue 14, remote kiosk) | Approved the `update_kiosk_settings` proposal | `approved`, with the proposal and its execution status | Live |
| Silence | `queue_count_changed` | No response within the link window | `none` | Live |
| Service reports it (`POST /learning/responses`) | `order_mismatch` (order A-77), `table_dirty` (table-4) | Remake / table cleared on the service's own screen | `service` link, 201; same `response_id` again adds nothing; a read or unknown tool returns 400 | Live, Unit |

### Simulated operator history

`learning/simulated/event_op_response.jsonl` holds 517 synthetic records generated by
`scripts/simulate_service_history.py`. The simulated operator follows a hidden policy
with noise:

| Service | Scenario | Event | Operator response |
|---|---|---|---|
| Kiosk | K1 | Queue ≥ 10 or wait ≥ 8 min | Express mode |
| Kiosk | K2 | Wait ≥ 8 min and a kiosk idle | Open one more kiosk |
| Kiosk | K3 | Queue ≥ 8 | Upsell prompts off |
| Kiosk | K4 | Queue < 5 twice in a row | Back to baseline settings |
| Weather | W1 | Rain or cold (≤ 11 °C) | Hot chocolate and tea on |
| Weather | W2 | Hot spell (≥ 28 °C) | Shake on |
| Weather | W3 | Rain stops | Hot drinks off again |
| Weather | W4 | Mild, dry drift | No response |
| Weather | W5 | Proposal in mild weather; one inconsistent one-off | Rejected ("not hot enough for shakes"); noise |
| Accuracy | A1 | Missing item, confidence ≥ 0.9, pickup counter | Remake the order (typed or approved proposal) |
| Accuracy | A2 | Confidence < 0.8 | Ignore (camera unsure) |
| Accuracy | A3 | Wrong item at the drive-through | Comp (typed; no comp tool exists) |
| Accuracy | A4 | Unclear case | Operator wants to look first |

### What the learner produced

Real learner run on Qwen3-30B-A3B INT4 (OVMS) over the simulated history:

| Service | Time | Rules | Learned rules (support = matching records / records the rule fires on) |
|---|---|---|---|
| Kiosk | 61 s | 7 | Queue ≥ 10 in standard mode → express; wait ≥ 8 min → open a kiosk; queue ≥ 8 → upsell off; short queue twice → back to normal |
| Weather | 40 s | 3 | ≥ 29 °C → shake on (8/8); raining and hot drinks off → hot chocolate and tea on (7/9); rain stops → hot drinks off (7/7) |
| Accuracy | 26 s | 1 | Confidence ≥ 0.91, missing item, pickup counter → remake, with the order id taken from the event (16/16) |

Not learned, as intended: A2 (ignore), A3 (comp has no tool), A4 (look first), W4 (no
response), and the W5 noise. Rules can test list items by id (for example whether tea
is already on the menu) and copy event values into arguments (the order id), and
approved rules are shown in plain words (for example "hot-chocolate on, tea on",
"order_id → the event's order_id").

### Learned skill applied live

With the approved `learned-kiosk` skill, a queue of 14 on the remote kiosk was decided
with skills `learned-kiosk` and `kiosk-operations`. The agent proposed express mode,
4 kiosks and upsell off, citing the operator rule; the operator approved and the
remote kiosk applied it.

### Plug-and-play learning (Unit)

A service with no agent code (table sim) sends `table_dirty` events with `table_id` and
`minutes_dirty`; operators clear tables dirty for 14 minutes or more. The learner
produces one rule, "minutes dirty ≥ 14 → `mark_table_cleared` with the event's
`table_id`", and the learned skill registers against the discovered tools.

### Learning tests

- Simulated dataset is valid, synthetic, and matches its generator; importing it twice adds nothing.
- Every service clears the default threshold of 20 responses.
- Weather rules are supported by the records; a remake with a fixed order id is dropped, while one bound to the event's order id is accepted.
- Menu list items are addressable by id; rule descriptions are not truncated.
- Chat calls map to catalog actions for any connected MCP server; service-reported responses are journaled.

### Learning limits

- The simulated accuracy events carry `confidence`, `station_type` and `issue_type`.
  Real Order Accuracy events carry `missing_items`, `extra_items`, `station`, `venue`
  and (dine-in) `accuracy_score`, so the simulated accuracy rule will not match real
  events. Learn from real journal records (operator remakes in chat) before relying on
  automatic remake proposals.
- Only kiosk learning was applied live; weather and accuracy rules were produced and
  checked against records, not run against live events.

## Tests

| Repository | Suite | Result |
|---|---|---|
| qsr-agent | `tests/autonomy/test_*.py`, `tests/operator_ui/test_*.py` (9 files, incl. new `test_discovery.py`, `test_remote_services.py`, `test_service_history.py`) | All OK |
| qsr-agent | `services/weather` unit tests | OK |
| order-accuracy take-away | `test_mcp_service.py`, `test_mcp_server.py`, `test_order_events.py` | 43 passed |
| order-accuracy dine-in | `tests/` (external `vlm_metrics_logger` stubbed) | 47 passed |
| smart-kiosk-assistant | `tests/unit/` | 349 passed, 9 failed. The 9 failures are all in `test_silero_vad.py` and fail the same way without these changes (VAD model not in the test image) |

New test coverage:

- **Agent:** take-away and dine-in merge into one `accuracy` service, each remake goes to the venue that flagged the order, one venue offline still answers; remote URLs replace the local simulations; discovery of unknown MCP services, retry when offline, disabled tools respected; chat calls journaled for any connected server; a discovered service learnable end to end.
- **Order Accuracy (both):** context shape the agent validates; remake accepted only for the latest flagged order and recorded as `remake_requested`; tool surface and `describe`; pushed events carry `service` and `venue`.
- **Kiosk:** context shape; `change_menu_items` bundle and rejections; `update_kiosk_settings` switches board, upsell and wait; queue events carry `service`, `previous_queue_count`, `estimated_wait_minutes`.

## Live Test Setup

The real service code ran in containers on the agent host as stand-ins for remote hosts:
kiosk QSR MCP on :8024 (port 8014 is an SSH tunnel to a real kiosk), take-away :8010,
dine-in :8011, a stand-in queue-service, and a hook that feeds validation results into
Order Accuracy exactly as its pipeline does. The agent's Hermes configuration listed only
the remote URLs for `kiosk`, `order-accuracy-take-away`, and `order-accuracy-dine-in`.

## Issues Found and Fixed During Live Testing

| Issue | Fix |
|---|---|
| Hermes sent a take-away remake to the dine-in server (both expose `request_remake`) | Events carry `data.venue`; chat names the deployment that owns the event; the skill routes by venue; tool descriptions and errors name the venue |
| The `order-accuracy` skill said the services were sensor-only with no actions | Skill updated for `request_remake` and venue routing |
| After restarting an Order Accuracy service, Hermes's MCP session expired and the remake outcome was unknown | Documented: restart the agent after restarting a service |
| A local order-accuracy simulation still started when remote order-accuracy URLs were set | The entrypoint skips a local simulation when a remote server with that name prefix is configured |

## Known Limits

- **Automatic remakes:** the agent does not propose a remake on its own until a learned accuracy skill exists; remakes are operator-led in chat.
- **Model reliability:** one take-away event decision failed after the model repeatedly requested a read its selected skills do not allow; it is recorded as `failed`.
- **Kiosk settings:** express mode sets the board flag (`simplified`), whose kiosk-ui wiring is a kiosk follow-up; `active_kiosks` is stored and used for the wait estimate only.
- **Event volume:** by default every validated order and every board change is sent to the agent, each costing a model call. Use `QSR_AUTONOMY_EVENT_TYPES=order_failed` and `KIOSK_CORE_QSR_AUTONOMY_EVENT_TYPES=queue_depth_sample`.
- **Security:** `/autonomy/events` and the Order Accuracy MCP ports have no authentication, and the event token is not checked. Keep them on the store network or behind an authenticating proxy.

## Changed Files

| Repository | Files |
|---|---|
| qsr-agent | `autonomy/discovery.py` (new), `autonomy/mcp.py`, `autonomy/service_capabilities.py`, `autonomy/worker.py`, `autonomy/learning.py`, `entrypoint.py`, `operator-ui/app.py`, `qsr-skills/order-accuracy/SKILL.md`, `.env.example`, `docs/user-guide/{how-it-works,api-reference,get-started/configuration}.md`, tests |
| order-accuracy | `take-away/src/core/agent_contract.py`, `dine-in/src/agent_contract.py` (new), `mcp_sensor.py` and `mcp_service.py` in both apps, both READMEs, both API references, tests |
| smart-kiosk-assistant | `kiosk_core/qsr_mcp/agent_tools.py` (new), `kiosk_core/qsr_mcp/{mcp_service,autonomy,board_state}.py`, `kiosk_core/config.py`, `kiosk_core/ordering/service.py`, `docker-compose.yml`, `docs/qsr-mcp.md`, tests |

See [Configuration](user-guide/get-started/configuration.md#run-kiosk-and-order-accuracy-on-remote-hosts)
for the deployment settings.
