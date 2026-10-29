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
| Current weather | `get_weather_details` (weather MCP service) | `condition`, `is_raining`, `temperature_c`, `source`, `simulated`, `observed_at` | Kiosk context has no weather. Include the source and say when `simulated` is true. |
| Store status, kiosks, or staffing | `get_kiosk_context` | `operations.status`, `operations.active_kiosks`, `operations.staff_on_duty` | Return only requested values, with useful nearby context when it changes the interpretation. |
| Kiosk mode, open kiosks, upsell prompts | `get_kiosk_context` | `operations.kiosk_mode`, `active_kiosks`, `max_kiosks`, `upsell_enabled`, `baseline_settings` | "Normal" settings means `baseline_settings`. |
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

`change_menu` and `change_menu_items` change operational state. A diagnostic
question never authorizes an action.

1. Call `get_kiosk_context` to resolve the exact item ID and current state.
2. Present the proposed item ID, availability and/or price, and reason.
3. Obtain explicit user approval in the current conversation.
4. Call `change_menu` with only approved values.
5. Report `executed`, `gate`, `status`, and `action_id` from the result.
6. If `placeholder` is true, explicitly say that no real kiosk was modified.

Never infer approval from urgency, a prior approval, or a request to analyze.
Autonomy-generated menu proposals follow the same rule: only the operator UI's
Approve action authorizes execution.

`change_menu_items` accepts one approved bundle of at most three availability
changes. Hermes event proposals are recommendations, not authorization; do not
call the tool until the matching proposal is approved.

## Kiosk Settings Actions

`update_kiosk_settings` changes ordering mode (`standard` or `express`),
`active_kiosks`, and `upsell_enabled` in one call; only supplied fields change.

An operator message that directly instructs a settings change (for example
"switch kiosks to express", "open kiosk 4", "turn off the upsell screens", or
"back to normal") is explicit approval for exactly that change:

1. Call `get_kiosk_context` for current settings, `max_kiosks`, and `baseline_settings`.
2. Call `update_kiosk_settings` once with only the fields that differ from the
   requested state and the operator's reason. "Open kiosk N" means
   `active_kiosks: N`; "back to normal" means `baseline_settings`.
3. Report the applied changes and say that the placeholder changed no real kiosk.

Questions or recommendations about settings never authorize a change.

## Owner Extension

Service owners should add specialized question mappings to the Tool Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md)
and keep live values out of this file.