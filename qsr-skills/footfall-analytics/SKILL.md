---
name: footfall-analytics
description: "Answer zone-level footfall, traffic, and busy-hour questions using the EdgeMart footfall-sim-service MCP service. Read-only — no actions."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Footfall, Traffic, Analytics]
---

# Footfall Analytics

Use the `edgemart-footfall-sim-service` MCP service for zone-level people-count
and density questions (entrance, counter, seating). This service is read-only
— it has no action tools, and no menu/table/order context; use
`cafe-operations` or `table-management` for those.

## Tool Routing

| User intent or question | Tool | Fields to use | Answer rule |
|---|---|---|---|
| Total traffic / footfall over a period | `get_total_footfall` | `total_footfall`, `event_count`, `by_zone[]` | Pass `zone` to scope to one zone, `start_date`/`end_date` to scope the period. State the period used. |
| When is the busiest time of day / rush hour | `get_busy_time_patterns` | `hour`, `total_footfall`, `days_observed`, `avg_footfall_per_day` | Report using `avg_footfall_per_day`, not raw `total_footfall`, so the answer isn't skewed by how many days were observed. |
| List known event types | `list_event_types` | `event_type`, `description` | — |

## Complex Questions

For "is it busier than usual" or staffing-style questions, call
`get_busy_time_patterns` once and reason over the hourly averages rather than
guessing. If the question also depends on orders or table turnover, use the
`cafe-operations` or `table-management` skill and its tool before combining
the answer.

## Owner Extension

Service owners should add specialized question mappings to the Tool Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md).
