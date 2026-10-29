# Make a Service Learnable: Quick Guide

[Operator-taught learning](self-learning.md) | [Adding a service](adding-a-service.md) |
[Service owner guide](SERVICE_OWNER_GUIDE.md)

Hermes learns **what operators do after your service's events** and proposes it
next time. You do not write the rules: you expose events, context, and one
action tool, and the learner writes `learned-<service>` from operator behaviour.

```text
your event -> event agent -> (nothing / proposal) -> operator acts or says what to do
           -> journal record -> "Learn now" card in the operator UI (or learn.py run)
           -> operator reviews rules and approves the skill (Hermes /skills approve)
           -> next similar event: Hermes proposes what operators did
```

The kiosk queue example (K1–K4) is fully implemented and is the reference for
everything below. Nothing in the learner, journal, or UI is kiosk-specific: a
new service gets its own card, review, and `learned-<service>` skill once its
events and tools follow this guide.

## 1. What Your Service Must Provide

| # | Piece | Kiosk reference | Why learning needs it |
|---|---|---|---|
| 1 | **Event** POSTed to `/autonomy/events` with a top-level `"service"` | `scripts/queue_event.py` | Groups records into `learned-<service>`; events without it are journaled as `unknown` and never learnt |
| 2 | **Context read tool** with the *current* value of everything your action changes, plus a baseline for "back to normal" | `get_kiosk_context` → `operations.kiosk_mode`, `active_kiosks`, `upsell_enabled`, `baseline_settings` | Rules say "only when not already set"; recovery rules restore the baseline |
| 3 | **One action tool per service** that bundles all settings (atomic, schema-validated) | `update_kiosk_settings(mode, active_kiosks, upsell_enabled, reason)` | The event agent proposes one action per event; several learned rules merge into one call |
| 4 | **Catalog registration** with `required_reads` and an owner **validator** | `kiosk.update_kiosk_settings` + `validate_kiosk_settings` in `autonomy/service_capabilities.py` | Learned skills may only use registered tools; the validator rejects stale context, no-ops, out-of-range values |
| 5 | **Hand-written chat skill** that tells Hermes a direct operator instruction is approval for that change | "Kiosk Settings Actions" in `qsr-skills/kiosk-operations/SKILL.md` | So "switch kiosks to express" in chat actually calls the tool and is logged as `tool_calls` |
| 6 | **MCP server registered with Hermes** (chat) | kiosk server in Hermes `mcp_servers` (done by `scripts/setup.sh`) | Chat Hermes can execute operator instructions |
| 7 | **Simulated history** generator with a hidden operator policy | `scripts/simulate_kiosk_history.py` | Bootstraps learning before real operators exist |
| 8 | *(Optional)* UI labels | `eventLabel()`, `actionTitle()`, `compactEventInfo()` in `operator-ui/static/index.html` | Readable banner and proposal titles |

Build services on `tests/mcp-services/service_base.py` (`QsrService`): its tool
calls are logged as JSONL in `MCP_LOG_DIR`, which is how live chat
`tool_calls` are captured. A custom service without that log still works, but
live records will only have the operator's text.

## 2. Step by Step

### 2.1 Emit events

```json
{"event_id": "queue-1a2b3c", "event_type": "queue_count_changed", "service": "kiosk",
 "store_id": "qsr-001", "occurred_at": "2026-10-23T12:00:00Z",
 "data": {"queue_count": 12, "previous_queue_count": 7, "estimated_wait_minutes": 9}}
```

- `service`: lowercase, `^[a-z][a-z0-9-]{0,39}$`. Use the service that **emits** the event
  (rain comes from `weather` even if the action changes the kiosk).
- `data`: flat numbers, booleans, short strings (≤ 30 chars). These become rule
  fields `event.<name>`. Fields ending in `_at` are ignored. Include the
  previous value when "changed twice in a row" matters (`previous_queue_count`).

### 2.2 Expose context

Return everything a rule might condition on, with `restaurant.id` (store-scoped
services) and a fresh `observed_at`. Rules reference it as
`context[<catalog tool>].<path>`, e.g.
`context[kiosk.get_kiosk_context].operations.kiosk_mode`.

### 2.3 Add one bundled action tool

```python
@svc.act_tool("update_kiosk_settings", level=GateLevel.AUTOMATIC,
              description="Apply one approved bundle of kiosk operating settings ...")
def update_kiosk_settings(reason: str, mode: str | None = None,
                          active_kiosks: int | None = None, upsell_enabled: bool | None = None) -> dict:
    ...  # validate, persist only supplied fields, return {"status": "accepted", "changes": ..., "placeholder": True}
```

Give it a JSON Schema with `"required": ["reason"]`, `"minProperties": 2`, and
`"additionalProperties": false`. Learned rules set **one argument each**; the
agent merges matching rules into one call, so every argument must be optional
except `reason`.

### 2.4 Register it for autonomy

Built-in services: add to `register_defaults()` in
`autonomy/service_capabilities.py`. External services: an extension module with
`register_autonomy(registry)` loaded via `QSR_AUTONOMY_MODULES` (see the
[service owner guide](SERVICE_OWNER_GUIDE.md#extension-module)).
Remote services served over Streamable HTTP (for example the EdgeMart cafe,
table, and footfall services) use `HttpMcpClient(url)` from `autonomy.mcp`
instead of `StdioMcpClient`, as the weather service does in
`autonomy/worker.py`. Registering them only in Hermes `mcp_servers` makes them
available to chat, not to event decisions or learning.

```python
catalog.register_tool(Capability(
    "kiosk.update_kiosk_settings", "Propose kiosk operating settings ...",
    kiosk, "update_kiosk_settings", False, ("kiosk.get_kiosk_context",), validate_kiosk_settings,
))
```

The validator must: check context freshness, reject values already in place,
enforce bounds (e.g. `active_kiosks <= max_kiosks`), require a reason.
A hand-written event `Skill` is optional: the learned skill lists the read and
action tools it needs. Leave the action **out of hand-written event skills** if
you want the before/after learning effect to be visible.

### 2.5 Let chat execute operator instructions

In your domain skill (`qsr-skills/<domain>/SKILL.md`) add a short section: read
context, then a direct instruction ("open kiosk 4", "back to normal") is
approval for exactly that change; call the action once with only the fields
that differ. Map phrases like "normal" to the baseline in context.

### 2.6 Write a simulator

Copy `scripts/simulate_kiosk_history.py` and change three things: the event
stream, the hidden policy, and the operator phrases. Each record is built with
`autonomy.learning.new_record(...)`:

```python
new_record(source="simulated", event={"event_id": ..., "type": "queue_count_changed",
           "service": "kiosk", "occurred_at": ..., "payload": {...}},
           kind="instruction" if acted else "none", text="open kiosk 4",
           tool_calls=[{"tool": "kiosk.update_kiosk_settings", "arguments": {"active_kiosks": 4, "reason": "..."}}],
           context={"kiosk.get_kiosk_context": {"operations": {...}}},
           link="generated", record_id=f"sim-kiosk-{seed}-{n:05d}")
```

Guidelines: deterministic seed; emit `kind="none"` for events where the operator
did nothing (negative evidence); vary the wording; add ~10% missed triggers and
one or two one-off instructions; keep context field names identical to what
your real context tool returns.

### 2.7 What the operator sees

No UI code is needed per service. The autonomy panel:

1. Shows the event banner above chat while the event is linkable, so a chat
   instruction is journaled against your event.
2. Shows *Hermes can learn from N &lt;service&gt; operator actions · Learn now*
   when the service reaches `QSR_LEARN_THRESHOLD` (default 20) unlearnt
   operator actions and one event type has `QSR_LEARN_MIN_EVENT_RECORDS`
   (default 5). Records with no operator response do not count.
3. Runs the learner in the background and opens a review of each rule
   (*When ... → setting*, *taught N× of M*, NEW tag).
4. **Approve skill** applies it through Hermes `/skills approve` and archives
   the records; **Reject** keeps them for the next run.

The learner profile is created on the first **Learn now**. Readable labels for
your event in the banner and proposal titles are optional (step 8 in the table
above).

## 3. Example Sets per Service

### Kiosk: queue events (implemented)

| ID | Event / condition | Operator says | Learned proposal |
|---|---|---|---|
| K1 | `queue_count_changed`, queue ≥ 10 | "switch kiosks to express, skip customisation" | `mode: express` |
| K2 | wait ≥ 8 min and a kiosk idle | "open kiosk 4" | `active_kiosks: +1` |
| K3 | queue ≥ 8 | "kill the 'add a drink?' screens" | `upsell_enabled: false` |
| K4 | queue < 5 twice in a row | "ok, back to normal" | restore `baseline_settings` |

### Weather: trigger-only service (actions land on kiosk / accuracy)

| ID | Event / condition | Operator says | Learned proposal | Tool to add |
|---|---|---|---|---|
| W1 | `weather_changed`, rain or < 12 °C | "put hot chocolate and tea up front" | feature hot drinks | `kiosk.set_featured_items` |
| W2 | > 28 °C | "it's hot, push shakes" | feature cold drinks | `kiosk.set_featured_items` |
| W3 | rain / storm | "double-check bags at drive-thru" | double-check on before errors rise | `accuracy.set_station_check` |
| W4 | clear again | "back to normal" | default featured items, double-check off | both |

To do for weather: add `"service": "weather"` to the event envelope in
`services/weather/weather_simulator/events.py` (it is missing today), and
include current featured items / station check mode in the kiosk and accuracy
context tools.

### Order accuracy: mismatch events

| ID | Event / condition | Operator says | Learned proposal | Tool |
|---|---|---|---|---|
| A1 | `order_mismatch`, missing item, confidence ≥ 0.9, pickup counter | "just remake the fries" | remake | `accuracy.request_remake` (exists) |
| A2 | confidence < 0.8 | "ignore, camera's unsure" | **no action** (learnt from `none`/rejected records) | — |
| A3 | wrong item, drive-thru | "car's gone, comp them $3" | comp instead of remake | `accuracy.issue_comp` (exists, needs approval) |
| A4 | `station_accuracy_changed`, < 90% / > 95% | "double-check bags at drive-thru" / "turn it off" | double-check on / off | `accuracy.set_station_check` |

For accuracy, emit the order's `confidence`, `issue_type` and `station_type` in
event `data` so rules can use them. Avoid notification-only actions: there is
nothing for the learner to verify.

## 4. When and How to Run

Host install (`PY=.venv/mcp/bin/python`). Compose: prefix with
`make learn ARGS="..."` / `make queue ...`.

| When | Command | Notes |
|---|---|---|
| Once per machine (optional) | `$PY scripts/learn.py setup` | Creates the `qsr-learner` Hermes profile with write approval on; **Learn now** does this on first use. Re-run after changing the model in `~/.hermes/config.yaml` |
| After adding the service | restart the operator UI | Catalog and MCP tools load at startup; learned skills reload on every event |
| Bootstrap (once per service) | `$PY scripts/simulate_<service>_history.py` then `$PY scripts/learn.py import learning/simulated/<file>.jsonl` | Commit the generated file; it is deterministic |
| Check readiness | `$PY scripts/learn.py status` | An event type is `ready` at `--min-records` (default 5) |
| Learn | Operator UI **Learn now** (shown at `QSR_LEARN_THRESHOLD`, default 20), or `$PY scripts/learn.py run [--service kiosk] [--min-support 2]` | ~1 min on Qwen3-30B-A3B; `--dry-run` prints the prompt only; `QSR_LEARN_AUTO=true` starts it automatically |
| Approve | Operator UI **Review → Approve skill**, or `$PY scripts/learn.py approve <id>` / `reject <id>` | Uses Hermes's `/skills approve` handler and archives records; interactive alternative: `hermes -p qsr-learner` → `/skills approve <id>` |
| Archive | automatic after UI/CLI approval, and within a minute after approving inside Hermes while the UI runs; otherwise `$PY scripts/learn.py finalize` | Moves learnt records to `learning/journal/learnt/`; rejected runs keep records unlearnt |
| Try it | send an event (e.g. `$PY scripts/queue_event.py --count 12 --wait 9`) | Proposal appears in the operator UI with `learned-<service>` in its skills |
| Live operation | nothing to run | UI journals chat instructions (event banner), approvals, rejections with reasons, and silent events |
| Periodically | nothing: the UI card appears when a service has enough new operator actions | Or schedule `learn.py run` + review |
| Roll back | restore a backup of `learning/skills/learned-<service>/SKILL.md`, or delete it | Takes effect on the next event |

## 5. Gotchas

- **Missing `service`** in the event: never learnt. Check `learn.py status`.
- **No Learn now card**: below the threshold, a change already waiting for
  review, or only `none` records. `GET /learning/status` shows `ready`,
  `pending`, and `learner.error`.
- **Learned skill not used**: the worker logs `skipped learned skill ...` when a
  listed tool is not registered or a required read is missing.
- **Context names drift**: if simulated context paths differ from the real
  tool's output, rules learnt from simulation will never match live events.
- **Overrides**: env such as `QSR_QUEUE_COUNT` beats simulated state; leave unset.
- **Small models**: the learner still verifies every rule against the records,
  and the event agent fills in matched settings the model omits; Qwen3-30B-A3B
  needs neither fallback in practice.
- **One action per event**: if a hand-written skill and a learned skill both
  apply, only one proposal is made.
- **Learner and events share the model**: event decisions wait while the
  learner runs (about a minute).

## 6. Done Checklist

- [ ] Event has `service`, unique `event_id`, flat decision fields in `data`.
- [ ] Context tool returns current values, baseline, `observed_at`, `restaurant.id`.
- [ ] One bundled action tool with schema; validator rejects no-ops and stale context.
- [ ] Capability registered with `required_reads` (HTTP services via `HttpMcpClient`); chat skill documents direct instructions.
- [ ] Simulator generates records that `learn.py import` accepts (with `none` records).
- [ ] **Learn now** appears for the service; the review shows rules matching your hidden policy; **Approve skill** succeeds.
- [ ] Replay: a matching event yields a proposal listing `learned-<service>`; a
      non-matching one yields no action; approval executes and context reflects it.
- [ ] Unit tests: service tool round-trip, validator, simulator determinism.
