# Self-learning for all applicable services: report

Status (updated 2026-11-03): **one common stimulation file in place; real learner runs against the model performed (sections J and K).** Kiosk learning works end to end. Weather and accuracy learn on the current engine in a host-side run, but weather was **not** reproducible in the container run (K). Sections F, I and the original L1/L2/L3 limitations were written against the older engine and are annotated with their current status.

## A. Summary

Requested: extend operator-taught self-learning beyond kiosk, generate synthetic data, and validate that Hermes consumes it.

Done:
- Investigated the existing flow. It is already per-service: `event.service` → `learned-<service>`. No architecture change was needed.
- Added a weather `service` field to weather events (the only source change).
- Added a synthetic generator and one common dataset (kiosk + weather + accuracy, 517 records).
- Added tests and this report.
- Real learner runs and approve/reject were done later (J, K). Open item: weather learning failed in the container run (K).

## B. Existing implementation (verified from code)

| Item | Finding |
|---|---|
| Capture | `operator-ui/app.py` `record_chat`/`record_proposal`/`record_silent_events` → `Journal.append` (`autonomy/learning.py`). Events come from `POST /autonomy/events`; chat `tool_calls` come from action calls in the MCP server logs (`action_calls_since`). |
| Store | `learning/journal/unlearnt.jsonl` (git-ignored), archived to `journal/learnt/<run>.jsonl` after approval. Dedup by record `id`. |
| Record schema | `new_record`/`validate_record`: `id`, `source` (`live`\|`simulated`), `ts`, `event{event_id,type,service,occurred_at,payload}`, `context{tool:snapshot}`, `agent{proposed}`, `operator{kind,text,tool_calls,reply?}`, `link`. `kind` ∈ instruction/approved/rejected/none. Service must match `^[a-z][a-z0-9-]{0,39}$`. |
| Import | `scripts/learn.py import FILE...` appends to the journal. Nothing auto-reads `learning/simulated/*.jsonl`; it must be imported. |
| Trigger | CLI: ≥ `--min-records` (default 5) non-`none` records per event type. UI: `QSR_LEARN_THRESHOLD` (default **20**) non-`none` records per service **and** ≥ `QSR_LEARN_MIN_EVENT_RECORDS` (5) for one event type, with no staged change (`ready_services`). `QSR_LEARN_AUTO` auto-starts. The "20–30" hypothesis is confirmed as the default 20 per service. |
| Learner | `learning_runner.run_service`: one model completion proposes JSON rules. `verify_rules` drops rules the records don't support (support ≥ 2, precision ≥ 0.6). The result is rendered deterministically into `learned-<service>/SKILL.md` and **staged** as a pending write in the learner Hermes profile. |
| Approval | Human only: UI Approve, `learn.py approve ID`, or `hermes -p qsr-learner` → `/skills approve`. Proposal = `pending/skills/<id>.json`. Persisted = `learning/skills/learned-<svc>/SKILL.md` exists and records are archived. |
| Consumption | `HermesEventAgent` reloads learned skills on every event and uses the section matching the event type; the skill may only use tools in its `metadata.qsr.tools`. |

## C. Architecture and design decisions

**1. File strategy: Option A (shared).**
- Evidence: the journal is one file and every record carries `event.service`. `learn.py import` takes many files. `counts_by_service`, `run_service` and the UI group by service.
- Separate files per service would add nothing: ids are service-prefixed and deduplicated.
- Rejected: Option B (no technical need); renaming the kiosk file (no benefit, risks the docs and tests that reference it).
- Rejected: a combined file. It would duplicate the kiosk records on import, or force regenerating the kiosk file.
- Chosen (revised): one shared stimulation file, `learning/simulated/event_op_response.jsonl`, holding kiosk, weather and accuracy. Records stay distinguishable by `event.service` and the service-prefixed id. The original `learning/simulated/kiosk-queue-history.jsonl` and `scripts/simulate_kiosk_history.py` are kept (tracked, used by `test_learning.py` and the docs); the common file's kiosk records are byte-identical to it, so importing both adds no duplicates.
- Migration risk: none. No schema change, and ids don't collide (tested).

**2. Services.**

| Service | Events | Operator/agent response | Outcome recorded | Include? | Reason |
|---|---|---|---|---|---|
| kiosk | `queue_count_changed` | `kiosk.update_kiosk_settings` | existing | already | existing |
| weather | `weather_changed` | `kiosk.change_menu_items` (cross-service) | `agent.proposed.status` | **yes** | Emits events, and its actions land on a registered tool. It lacked `service` (fixed). |
| accuracy | `order_mismatch_detected` | `accuracy.request_remake`; comp is typed only | `agent.proposed.status` | **yes (data only)** | With the current engine, `request_remake` can be learned: `order_id` is bound from the event (`{"from": "event.order_id"}`). On the older engine this was blocked (L1, now resolved). |
| loss-prevention, suspicious-activity (SAD), footfall, edgemart sim, table sim | SAD pushes eligible critical events to `/autonomy/events` (`SAD_EVENT_HUB_URL`); the others were not found to post | read-only skills | n/a | no | No registered autonomy action tool, so operators have nothing to teach or approve. Real SAD event envelope not read (SAML SSO blocked); not verified. |
| digital-signage, cafe-ops/table (cleared) | none | chat-only actions | n/a | no | Remote MCP via chat only; not in the autonomy catalog, so their calls aren't captured as `tool_calls`. Gap, not invented. |
| Hermes gateway/UI/store/health | infrastructure | — | — | no | No learning signal. |

**2a. What a service needs to become learnable** (selection was by capability, not by name):
1. An event POSTed to `/autonomy/events` whose service can be determined. The current producers (kiosk, Order Accuracy, weather) send a top-level `service`. When it is absent, `autonomy/learning.py` infers it from the event type (default map: `order_mismatch` and `order_mismatch_detected` → `accuracy`; extend with `QSR_EVENT_SERVICES=type=service,...`). Events whose service cannot be determined are journaled as `unknown` and never learnt. (Older note that producers omit `service` no longer applies.)
2. A context read tool returning current state.
3. An action tool registered in `autonomy/service_capabilities.py` with a validator.
4. Rule-engine fit: scalar event fields and list items addressed by `id` as conditions; action arguments are constants or bound from an event field.

Simulated vs live differences: the kiosk data copies `scripts/queue_event.py` (sets `service: kiosk`, has `previous_queue_count`), not the real voice-kiosk payload (`queue_count`, `source`, `source_event_type`); accuracy `data` fields (confidence, station_type, issue_type) are assumptions. Rules conditioned on a field that live events lack will simply not match live events; re-learn from live records once they accumulate.

**3. Schema compatibility.**
- The existing schema is used exactly. Synthetic records are marked with `source: "simulated"`, an id prefix `sim-`, and `payload.simulated`/`payload.source`. No new field.

**4. Cross-service.**
- Weather → kiosk action: **supported** (the learner prompt for `weather` includes kiosk tools, and rules propose `kiosk.change_menu_items`). Learned end to end in the host-side run (J2); see K for the container result.
- Accuracy → kiosk, and a final outcome beyond `proposed.status`: possible through `context[...]` snapshots and ids only. There is no explicit causal link or result field. A new architecture would be needed, so it goes to the team list.
- No automatic cross-service actions were implemented.

## D. Changes made

The rows below are the changes made for this task. The working tree also contains engine and service-routing changes from a separate effort (not covered here): `autonomy/learning.py`, `autonomy/mcp.py`, `autonomy/service_capabilities.py`, `autonomy/worker.py`, `autonomy/discovery.py`, `operator-ui/app.py`, `docker-compose.yaml`, `.env.example`, `entrypoint.py`, the order-accuracy skill, and user-guide docs. See `docs/remote-services-report.md`. Commit them separately.

| File | Change | Why |
|---|---|---|
| `services/weather/weather_simulator/events.py` | add `"service": "weather"` to the envelope | Without it, live weather events are journaled as `unknown` and never learnt. The docs listed this as missing; it is additive (the autonomy validator ignores extra top-level keys). |
| `services/weather/tests/test_weather_simulator.py` | assert the new field | covers the change |
| `scripts/simulate_service_history.py` | new deterministic generator; `simulate_all()` reuses `simulate_kiosk_history.simulate` unchanged plus weather and accuracy scenarios, and writes the common file | reuses the logger and format; one entry point; fails on duplicate ids |
| `learning/simulated/event_op_response.jsonl` | generated, 517 records | the common stimulation dataset (the intermediate `learning/simulated/accuracy-weather-history.jsonl` was removed: untracked and fully contained in it) |
| `tests/autonomy/test_service_history.py` | new tests | see G |
| `docs/backup/self-learning-integration.md` | one line: weather `service` now present | keeps the docs accurate |

Untouched: autonomy controller/event agent, learning engine, the learner runner, the operator UI, the MCP servers, the kiosk data and generator, approval flow, and all configs.

## E. Stimulation dataset

- File: `learning/simulated/event_op_response.jsonl`: static, synthetic (`source: "simulated"`, ids `sim-<service>-<seed>-<n>`), same schema as before.
- Regenerate: `python scripts/simulate_service_history.py` (`--days 8 --seed 7 --out FILE`; byte-identical on rerun).
- Validate: `python -m unittest tests.autonomy.test_service_history` (every record through `validate_record`, unique ids, equals generator output, kiosk records equal the original kiosk file).
- 517 records, all ids unique:

| Service / event | none | instruction | approved | rejected | non-none |
|---|---|---|---|---|---|
| kiosk / `queue_count_changed` | 382 | 48 | 0 | 0 | 48 |
| weather / `weather_changed` | 26 | 23 | 1 | 1 | 25 |
| accuracy / `order_mismatch_detected` | 10 | 24 | 1 | 1 | 26 |

  Each service clears the UI threshold (20 non-none responses, 5 for one event type). The kiosk file has many `none` records because ignored events are recorded as negative evidence.
- **Live vs synthetic:** the file is never written by the app. Live operator chats, approvals, rejections and silent events go through `operator-ui/app.py` → `Journal.append` into `learning/journal/unlearnt.jsonl`, unchanged. Import the stimulation file only into a disposable journal:
  `QSR_LEARNING_DIR=/tmp/qsr-test python scripts/learn.py import learning/simulated/event_op_response.jsonl` (re-import adds 0).
- Weather scenarios:
  - W1 rain or cold → hot drinks on.
  - W3 rain stops → hot drinks off.
  - W2 heat ≥ 28 °C → shakes on.
  - W4 dry drift → no response.
  - A "still raining, already on" case → no response.
  - One missed response (noise).
  - One rejected proposal (negative: mild weather, no shakes).
  - One approved/executed proposal (outcome).
  - One inconsistent one-off (should not become a rule).
- Accuracy scenarios:
  - A1 high-confidence missing item at the pickup counter → remake.
  - A2 low confidence → ignore (none, or a rejected proposal).
  - A3 wrong item at the drive-through → comp (text only, because `issue_comp` isn't a registered autonomy tool, so live records wouldn't carry a call either).
  - A4 unclear → "check the camera first" (do nothing / clarify).
- Why this size (weather/accuracy): 8 days gives about 3 consistent responses per day per rule family, so each rule clears `min_support` 2 and the UI threshold 20 with variation. Experiment: the CLI marks an event type "ready" at 5, and a rule is kept at support ≥ 2 with precision ≥ 0.6.
- No production store or service was touched, and no action was executed.

## F. Hermes validation (initial, before the model was available; superseded by J and K)

**Verified:**
- Re-checked after consolidation: `learn.py import` of the common file into a disposable journal added 517 of 517; importing it again, or the old kiosk file, added 0.
- Model endpoint `127.0.0.1:4444` was down in earlier checks; on 2026-10-30 `GET /v3/models` returned 200 (OpenVINO/Qwen3-30B-A3B-Instruct-2507-int4-ov). A real learner run has still NOT been performed.
- `learn.py status` showed accuracy 26, kiosk 48 and weather 25, all `ready`.
- `learn.py run --dry-run --service weather` produced a learner prompt built from the weather records, with the right event/field summary and kiosk action tools (cross-service).
- Deterministic checks (no model):
  - `induce_missing_rules` + `verify_rules` independently recover the weather `temperature_c ≥ 29 → shake on` rule (8 of 8).
  - Hand-written stand-in "model" rules for rain-start and rain-stop are accepted (7 of 8, 0 rejected).
  - On the older engine a remake rule was rejected (L1). The current engine binds `order_id` from the event and accepts it (J2).
- Sandbox run of the real `run_service` with **only the model call stubbed**, using a copied learner profile:
  - It kept 3 verified rules and staged pending write `a9994c19`.
  - `learned-weather/SKILL.md` did **not** exist before approval, which confirms a proposal is not a persisted change.

**Blockers at that time (all later resolved, see J and K):** model endpoint down; Hermes launcher pointing at a deleted interpreter (exit 127); approval stalling on a one-time source-update build.

**Reproduce:**
1. Start the model server, then the operator UI.
2. Run `QSR_LEARNING_DIR=<disposable dir> python scripts/learn.py import learning/simulated/event_op_response.jsonl` (use the same dir for the UI, via `QSR_LEARNING_DIR`).
3. The UI "Learn now" card should appear for weather (25 ≥ 20) and accuracy (26 ≥ 20). Equivalent CLI: `learn.py run --service weather`, then `learn.py pending`, then `learn.py approve <id>`.
4. Check that `learning/skills/learned-weather/SKILL.md` exists.
5. Use `QSR_LEARNING_DIR` and `QSR_LEARNER_HERMES_HOME` pointing at a copy to avoid touching real state.

**Result:** see J and K. Weather and accuracy do produce rules on the current engine; the earlier inference that accuracy would produce none only applied to the older engine.

## G. Test results

Run with a temp venv (`fastmcp`, `pyyaml`), because the system Python lacks `fastmcp`:

| Command | Result |
|---|---|
| `python -m unittest discover -s tests/autonomy` (current tree, includes the engine changes) | 100 passed |
| weather: `cd services/weather && PYTHONPATH=. python -m unittest discover -s tests` | 18 passed |
| `python -m unittest discover -s tests/mcp-services` | 19 passed |
| `python -m unittest discover -s tests/operator_ui` | 6 passed |

- Without `fastmcp`, one existing test (`test_stdio_mcp_client_reads_and_acts_on_fastmcp_service`) and the weather and mcp-services suites fail on import. That is an environment issue unrelated to the change, not a weakened test.
- Frontend tests were not run (no UI change).
- New tests cover: JSONL validity and generator determinism, mixed services in one journal, idempotent import, kiosk backwards compatibility, id collisions, synthetic marking, the weather `service` envelope, malformed and sparse records, the threshold, and rule verification.

## H. Questions for the team

1. **Learning from outcomes.** Should learning use only approved/successful outcomes, or also rejections and silent events? (Today both are used as negative evidence.)
2. **Accuracy → action.** Should an accuracy failure ever drive a kiosk action, or only a recommendation for operator approval?
3. **Cross-service relationships.** Should they be learned? The schema has no explicit causal link or action result (only `proposed.status`).
4. **Remake rules.** Resolved: the engine now binds an argument from an event field. Confirm that is the intended design.
5. **Comp.** Should `issue_comp` become an autonomy tool? It is approval-gated today.
6. **Approval.** Who approves memory/skill changes, and per service or global?
7. **Sharing.** Should learned skills be service-specific (as now) or shared?
8. **Conflicts.** What happens if a learned skill conflicts with a business rule? (Today the tool's `validate_*` still gates it.)
9. **Privacy.** What must be excluded from journals? (Today `compact_context` just caps size; operator text is stored as typed.)
10. **Producer envelope.** Largely resolved: producers send `service`, and qsr-agent infers it from `event_type` when absent. Is the default type→service map complete?
11. **Real payloads.** What are the real Order Accuracy and SAD `data` fields? Should SAD, loss-prevention and digital-signage get autonomy action tools?
12. **Threshold.** Is the 20-per-service and 5-per-event default intended for production?

## I. Follow-up recommendations

**Essential before declaring the flow validated:**
- Find out why weather learning fails in the container but works host-side (K). Compare the tool schemas the learner sees (`QSR_MCP_PYTHON`) and the raw model reply in both.
- Observe the UI "Learn now" popup, and a learned skill changing a live event decision.

**Optional:**
- **L1: argument binding from event fields.** RESOLVED in the current engine (`{"from": "event.<field>"}`); verified by a real accuracy run (J2).
- **L2: list fields.** RESOLVED in the current engine: list items are addressable by `id` (e.g. `menu.items.shake.available`). Older notes: `_flatten` dropped lists.
  - Menu `changes` includes per-item free-text `reason`, and rules match on the exact JSON. Live operator phrasing would split support.
- **L3: instrumentation gaps.**
  - Live producers now send `service` (kiosk, Order Accuracy), and the weather simulator sets it. The older claim that accuracy and voice-kiosk events lack `service` is obsolete.
  - Still assumptions: the accuracy `data` fields (confidence, station_type, issue_type) in the simulated data are not the real payload.
  - Remote services (loss-prevention, digital-signage and others) have no event or action path into the journal.
- **L4: EdgeMart table service (not integrated).**
  - It exposes `table.dirty`/`table.cleared` events and a `mark_table_cleared` action, so it could be added later.
  - Nothing exists for it in this repo yet: no skill file, no registered tool or validator, no event bridge, no synthetic history.
  - To add it: a `table` skill under `qsr-skills/`, tool registration with a "table is dirty" validator, a bridge posting events with `service: table` to `/autonomy/events`, an HTTP client that parses text-only MCP results, and synthetic records.
  - Status: deferred until the skill and its tools exist.

## J. Real learner run against the model (2026-11-02)

Setup: disposable journal (`QSR_LEARNING_DIR`), a copy of the `qsr-learner` profile (`QSR_LEARNER_HERMES_HOME`), `QSR_MCP_PYTHON=/tmp/mcpenv/bin/python`. Model: `127.0.0.1:4444` (real, no stubs).

**Verified**
- **Kiosk:** the learner kept 7 verified rules and staged a `learned-kiosk` pending write. Reject left no skill file and the records stayed unlearnt. After a re-stage, `learn.py approve` wrote `skills/learned-kiosk/SKILL.md` and archived the 48 kiosk records to `journal/learnt/`. Proposal, rejection, approval and persistence are all confirmed.
- **Weather (older engine, now superseded by J2):** NOT learnable then.
  - Without tool schemas the model guessed two flat arguments (`item_id`, `available`) and every rule was dropped with "exactly one argument". The schemas did not load because `.venv/mcp/bin/python` does not exist here. Setting `QSR_MCP_PYTHON` fixes that (`change_menu_items` has one argument, `changes`).
  - With schemas loaded, every rule is still dropped: the model conditions on menu state (`context[kiosk.get_kiosk_context].menu.items...`), but `_flatten` drops list fields (L2), so those fields do not exist.
  - Diagnostic only (nothing staged): removing the list conditions from the model's real reply and running `verify_rules` accepted `temperature_c >= 29 → shake on` (8/8) and `rain stopped → hot drinks off` (7/8). The "rain → hot drinks on" rule fails at 7 of 16 because the "already on, do nothing" records cannot be told apart without menu state.
  - Fixing this needs a team decision, not a data change: flatten list items by `id` in `_flatten`, or tell the learner prompt which context fields are addressable.

**Hermes runtime failure (root cause and fix)**
- `hermes --print-runtime-command` exited 127 because `~/.hermes/hermes-agent/.hermes/bin/hermes` (and `hermes-acp`) hard-coded `/tmp/qsr-learner-home/tools/python-3.14.7.../bin/python3`. A Hermes bootstrap run during my earlier sandbox test with `HERMES_HOME=/tmp/qsr-learner-home` rewrote the wrappers, and that directory no longer exists.
- Fix: both wrappers now point at `~/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3` (backups: `*.bak-tmp-python`).
- The approve/reject handler then hung for more than 120s: Hermes owed a "finish interrupted source update" build, which my earlier timeouts had kept killing. Letting it run once (about 20s to complete after the build) cleared it; approve/reject now run normally.

**Important finding:** the real `qsr-learner` profile's `skills.external_dirs` and `create_dir` point at `/home/intel/udit-ws/from-fork/qsr-agent/learning/skills`, a different checkout that already contains a real `learned-kiosk`. Approving there would not use this repo's `learning/skills`. Run `scripts/learn.py setup` to repoint a profile at the journal you intend to use (done for the disposable copy only).

**Left as is:** the pending proposal `6b357b24` (a leftover test proposal, stored in `~/.hermes/profiles/qsr-learner/pending/skills/6b357b24.json`). Approving it would fail because `learned-kiosk` already exists there. To clear it: `python scripts/learn.py reject 6b357b24`.

### J2. Same checks on the current engine (host-side, real model, disposable journal and copied profile)

- **Weather:** the learner kept 3 verified rules and staged them. Approval wrote `learned-weather/SKILL.md`. The L2 blocker no longer applies (list items addressable by id).
- **Accuracy:** 1 verified rule (`request_remake` with `order_id` bound from the event) was staged. Reject left no skill file.

## K. Container end-to-end run of this tree (2026-11-03)

Image `intel/qsr-agent:selflearn-all` (its `learning.py`, `service_capabilities.py`, `discovery.py`, `operator-ui/app.py`, `learning_runner.py`, `worker.py`, `mcp.py`, `entrypoint.py` match the working tree). Separate ports (UI 8601, weather 8091), own volumes, real model on 4444, real remote Order Accuracy and kiosk MCP hosts. The existing stack was untouched; the test stack and volumes were removed afterwards.

| Check | Result |
|---|---|
| `/ready`, `/autonomy/status`, `/learning/status` | OK |
| Chat: weather, accuracy mismatches, kiosk queue | correct answers from live remote hosts |
| Chat: "What is 2+2?" | refused with the standard scope message |
| Import of the common file | 517 added; re-import 0 added |
| `/learning/status` ready | accuracy 26, kiosk 48, weather 25 |
| Kiosk learn, then approve | `learned-kiosk` staged (9 verified rules), approved, `skills/learned-kiosk` persisted, kiosk records archived |
| Accuracy learn, then reject | 1 verified rule staged, rejected, no skill written, records stay unlearnt |
| Weather learn (3 runs) | **FAILED**: every rule dropped ("taught 0x of 7 matching"), so no proposal staged |
| Posting an event by hand | not completed: my payload put fields at the top level instead of inside `data` and was rejected (`data must be an object`); use the envelope in `docs/user-guide/api-reference.md` |

Not run: the UI "Learn now" popup; a learned skill changing a live decision; the earlier "read is not permitted" decision failure.

**Weather failure, open.** The rules match records (7 to 9 each) but the proposed action argument never equals what operators did, so support is 0. The host-side run on the same code kept 3 rules, so the difference is environmental (tool schemas from `QSR_MCP_PYTHON`, or model output). Not yet diagnosed.
