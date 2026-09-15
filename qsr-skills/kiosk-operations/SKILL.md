---
name: kiosk-operations
description: "Answer restaurant, kiosk, queue, wait-time, staffing, menu availability, and ordering-activity questions; safely handle kiosk menu-change requests using the kiosk MCP service."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Kiosk, Queue, Menu, Restaurant-Operations]
---

# Kiosk Operations

Use the kiosk MCP service as the only source of live kiosk and restaurant-state
facts. Never answer an operational question from memory or an earlier turn when
a fresh context call is available.

## Tool Routing

| User intent or question | Tool | Fields to use | Answer rule |
|---|---|---|---|
| Current queue or guests waiting | `get_kiosk_context` | `operations.queue_count`, `observed_at` | State the count and observation time. Do not convert orders into people. |
| Current wait time | `get_kiosk_context` | `operations.estimated_wait_minutes`, `observed_at` | Say that the value is an estimate and include minutes. |
| Store status, kiosks, or staffing | `get_kiosk_context` | `operations.status`, `operations.active_kiosks`, `operations.staff_on_duty` | Return only requested values, with useful nearby context when it changes the interpretation. |
| Menu price or availability | `get_kiosk_context` | `menu.active_menu_id`, matching entry in `menu.items` | Match by stable `id` when available; otherwise match the displayed name exactly and state ambiguity. |
| Recent demand or kiosk activity | `get_kiosk_context` | `recent_activity.orders_last_15_minutes`, `top_item`, `abandoned_sessions` | Preserve the service's time window and distinguish orders from sessions. |
| Any other kiosk or restaurant-state analysis | `get_kiosk_context` | All returned fields relevant to the question | Call once, reason over the snapshot, show calculations briefly, and state any missing evidence instead of guessing. |

## Complex Questions

For comparisons, recommendations, causes, or open-ended questions, call
`get_kiosk_context` once. Select the relevant fields from that single snapshot,
perform transparent arithmetic, distinguish facts from recommendations, and
include `observed_at`. If the question also depends on another domain, use that
domain's skill and context tool before synthesizing the answer.

## Menu Actions

`change_menu` changes operational state. A diagnostic question never authorizes
an action.

1. Call `get_kiosk_context` to resolve the exact item ID and current state.
2. Present the proposed item ID, availability and/or price, and reason.
3. Obtain explicit user approval in the current conversation.
4. Call `change_menu` with only approved values.
5. Report `executed`, `gate`, `status`, and `action_id` from the result.
6. If `placeholder` is true, explicitly say that no real kiosk was modified.

Never infer approval from urgency, a prior approval, or a request to analyze.

## Owner Extension

Service owners should add specialized question mappings to the Tool Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md)
and keep live values out of this file.