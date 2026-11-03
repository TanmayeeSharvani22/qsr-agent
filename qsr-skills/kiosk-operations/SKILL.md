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
| Current queue or guests waiting | `get_kiosk_context` | `operations.queue_count`, `queue_status`, `people_nearby`, `observed_at` | State the count and observation time. If `queue_available` is false, say the queue camera is unavailable. Do not convert orders into people. |
| Current wait time | `get_kiosk_context` | `operations.estimated_wait_minutes`, `observed_at` | Say that the value is an estimate and include minutes. |
| Current weather | `get_weather_details` (weather MCP service) | `condition`, `is_raining`, `temperature_c`, `source`, `simulated`, `observed_at` | Kiosk context has no weather. Include the source and say when `simulated` is true. |
| Store status or kiosks | `get_kiosk_context` | `operations.status`, `operations.active_kiosks`, `operations.max_kiosks` | Return only requested values. The kiosk does not report staffing; say so if asked. |
| Kiosk mode, open kiosks, upsell prompts | `get_kiosk_context` | `operations.kiosk_mode`, `active_kiosks`, `max_kiosks`, `upsell_enabled`, `baseline_settings` | "Normal" settings means `baseline_settings`. |
| Menu price or availability | `get_kiosk_context` | matching entry in `menu.items` (`id`, `name`, `category`, `price`, `available`) | Match by `id` (for example `DRINK-004`) when available; otherwise match the displayed name and state ambiguity. |
| Recent demand | `get_kiosk_context` | `recent_activity.orders_last_15_minutes`, `top_item` | Preserve the service's time window. |
| Queue trend ("is it always busy now?") | `get_queue_history` (`period`: `today`, `yesterday`, `all`, `YYYY-MM-DD`) | `samples`, `avg_count`, `max_count` | Name the period and sample count. |
| Orders, revenue, best sellers for a day | `get_order_stats` (`period`, `top_n`) | order count, revenue, top items | Name the period. |
| Menu-board mode (full or simplified) | `get_board_state` | mode, when and why it changed | Report the reason when present. |
| Menu changes waiting for approval | `get_menu_requests` (`status`) | requests and their status | List pending requests oldest first. |
| Any other kiosk or restaurant-state analysis | `get_kiosk_context` | All returned fields relevant to the question | Call once, reason over the snapshot, show calculations briefly, and state any missing evidence instead of guessing. |

## Complex Questions

For comparisons, recommendations, causes, or open-ended questions, call
`get_kiosk_context` once, plus `get_queue_history` or `get_order_stats` when the
question is about a period. Select the relevant fields, perform transparent
arithmetic, distinguish facts from recommendations, and include `observed_at`.
If the question also depends on another domain, use that domain's skill and
context tool before synthesizing the answer.

## Menu Actions

`change_menu_items`, `update_menu_item`, `add_menu_item` and `set_board_mode`
change operational state. A diagnostic question never authorizes an action.

1. Call `get_kiosk_context` to resolve the exact item ID and current state.
2. Present the proposed item ID, availability and/or price, and reason.
3. Obtain explicit user approval in the current conversation.
4. Call `change_menu_items` for availability (up to three items), or
   `update_menu_item` (`product_id`, `price`, `is_available`) for a price or a
   single item, with only approved values.
5. Report what the result says was applied. If the kiosk queues the change for
   its own operator approval (`get_menu_requests`), say it is pending there.

Never infer approval from urgency, a prior approval, or a request to analyze.
Autonomy-generated menu proposals follow the same rule: only the operator UI's
Approve action authorizes execution.

Hermes event proposals are recommendations, not authorization; do not call an
action tool until the matching proposal is approved.

## Kiosk Settings Actions

`update_kiosk_settings` changes ordering mode (`standard` or `express`),
`active_kiosks`, and `upsell_enabled` in one call; only supplied fields change.
Express mode also simplifies the kiosk's menu board.

An operator message that directly instructs a settings change (for example
"switch kiosks to express", "open kiosk 4", "turn off the upsell screens", or
"back to normal") is explicit approval for exactly that change:

1. Call `get_kiosk_context` for current settings, `max_kiosks`, and `baseline_settings`.
2. Call `update_kiosk_settings` once with only the fields that differ from the
   requested state and the operator's reason. "Open kiosk N" means
   `active_kiosks: N`; "back to normal" means `baseline_settings`.
3. Report the applied changes from the result's `settings`.

Questions or recommendations about settings never authorize a change.

## Owner Extension

Service owners should add specialized question mappings to the Tool Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md)
and keep live values out of this file.