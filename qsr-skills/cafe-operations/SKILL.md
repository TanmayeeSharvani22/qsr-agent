---
name: cafe-operations
description: "Answer café-day questions — customer arrivals/departures, orders, table occupancy, and queue depth — using the EdgeMart sim-service MCP service. Safely handle table-cleared and manual event actions."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Cafe, Orders, Queue, Restaurant-Operations]
---

# Café Operations

Use the `edgemart-sim-service` MCP service as the source of café-day facts:
customer arrivals/departures, orders, table occupancy, and queue depth. Never
answer from memory or an earlier turn when a fresh tool call is available.

## Tool Routing

| User intent or question | Tool | Fields to use | Answer rule |
|---|---|---|---|
| What's happening right now (tables, queue) | `get_current_snapshot` | per-ref `event_type`, `occurred_at`, `payload` | One row per table/queue/active customer. State the latest event type and when it occurred. |
| Order/customer/table counts over a period | `query_history` | `period`, `event_type`, `count` | Pass `group_by` (`day` or `hour`), `start_date`/`end_date`. Report counts per period, don't invent missing periods. |
| How today compares to another day | `compare_to_baseline` | `current`, `baseline` (per `event_type` counts) | Requires both `date` and `baseline_date`. State the delta per event type, not just raw numbers. |
| Recent raw activity / "what just happened" | `tail_events` | `event_type`, `ref`, `occurred_at`, `payload` | Use `since_id` to avoid re-reporting events already described this conversation. |
| List known event types | `list_event_types` | `event_type`, `description` | Use to explain what this service can report on. |
| Any other café-operations analysis | `query_history` or `get_current_snapshot` | All returned fields relevant to the question | Call once, reason over the result, show arithmetic briefly, state any missing evidence instead of guessing. |

## Complex Questions

For comparisons, trends, or open-ended questions, call the narrowest tool that
answers it (prefer `compare_to_baseline` over two separate `query_history`
calls for a two-date comparison). Include the date range used in the answer.

## Actions

`mark_table_cleared` and `inject_event` change operational state.

1. Call `get_current_snapshot` (check the row for the target `ref`) or
   `tail_events` (filtered to events for that `ref`) first to confirm the
   table/ref and its current state — this service has no `get_table_history`
   tool; that's `table-management`'s tool for `edgemart-table-sim-service`.
2. Present the proposed change and reason.
3. Obtain explicit user approval in the current conversation.
4. Call the action tool with only approved values.
5. Report the returned `event` (its `event_type`, `ref`, `occurred_at`).

Never infer approval from urgency or a request to analyze. A diagnostic
question never authorizes an action.

## Owner Extension

Service owners should add specialized question mappings to the Tool Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md).
