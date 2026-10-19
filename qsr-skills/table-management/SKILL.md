---
name: table-management
description: "Answer table occupancy, utilization, and dirty-table questions, and safely mark tables occupied/cleared, using the EdgeMart table-sim-service MCP service."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Tables, Cleaning, Restaurant-Operations]
---

# Table Management

Use the `edgemart-table-sim-service` MCP service as the source of table
occupancy/cleaning facts. It tracks only the table lifecycle (occupied, dirty,
cleared) — it has no customer or order context; use the `cafe-operations`
skill for those.

## Tool Routing

| User intent or question | Tool | Fields to use | Answer rule |
|---|---|---|---|
| How utilized is a table / are tables | `get_utilization` | `tables[].ref`, `occupied_seconds`, `cycles`, `utilization` | Pass `table_ref` to scope to one table; omit for all tables. State the period used. |
| How long do tables sit dirty before cleaning | `get_dirty_duration_stats` | `overall`/`by_table` `count`, `avg_seconds`, `min_seconds`, `max_seconds` | A table still dirty right now is included, measured up to now — note this if relevant. |
| Full history for one specific table | `get_table_history` | `event_type`, `occurred_at`, `payload` | `table_ref` is required. Most recent first; state how many rows were returned vs. the `limit`. |
| Which tables are dirty right now | *(no single tool covers this — see note below)* | — | Call `get_table_history` per table and check the latest `event_type`, or state the limitation. |
| List known event types | `list_event_types` | `event_type`, `description` | — |

**Known gap:** this service has no cross-table "current status" tool (unlike
`cafe-operations`'s `get_current_snapshot`). Don't claim a definitive list of
"all dirty tables" unless you've actually checked each table's latest event.

## Actions

`mark_table_occupied` and `mark_table_cleared` change operational state.

1. Call `get_table_history` for the target table to confirm its current state
   before proposing a change.
2. Present the proposed change (`table_ref`, new state) and reason.
3. Obtain explicit user approval in the current conversation.
4. Call the action tool with only the approved `table_ref`.
5. Report the returned `event` (`event_type`, `ref`, `occurred_at`).

Never infer approval from urgency or a request to analyze. A diagnostic
question never authorizes an action.

## Owner Extension

Service owners should add specialized question mappings to the Tool Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md).
