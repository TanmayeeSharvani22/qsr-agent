---
name: smart-kiosk
description: "Answer kiosk queue-depth, queue-trend, order-stats, and menu-board-state questions, and simplify/restore the on-screen menu board, for the Smart Kiosk Assistant MCP service."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Kiosk, Queue, Orders, Menu-Board]
---

# Smart Kiosk Assistant

Use the `smart-kiosk` MCP service as the only source of live kiosk queue,
order, and menu-board facts. Never answer from memory or an earlier turn when
a fresh tool call is available.

## Contract Discovery

Before the first smart-kiosk tool call in a conversation, call `describe`.
Use the returned contract to identify the current read tools, action tools,
input schemas, event types, and action gates — do not assume this file's
tables stay accurate if `describe` reports something different; re-derive
routing from the live contract in that case. Do not use `describe` as
evidence for live queue/order/board facts.

Map each request to the required capability below, then choose the compatible
tool from `describe`. If no compatible tool is available, explain that the
service contract does not support the request rather than guessing.

Unlike Order Accuracy and Suspicious Activity, Smart Kiosk is both a sensor
and an actuator: it exposes one action tool, `set_board_mode`, in addition to
its read tools.

## Capability Routing

| User intent or question | Required capability | Fields to use | Answer rule |
|---|---|---|---|
| Current queue length / how busy is the kiosk right now | Retrieve current queue depth and status | `count`, `nearby`, `status` (LOW/MEDIUM/HIGH), `timestamp` | Report the count and status (LOW/MEDIUM/HIGH); mention `nearby` only if it is non-zero or asked about. |
| Is the queue usually deep at this time / queue trend for a period | Retrieve queue-depth trend for a period (`today`\|`yesterday`\|`all`\|`YYYY-MM-DD`) | `period`, `samples`, `avg_count`, `max_count` | Report average and max depth for the requested period, and how many samples that is based on. |
| Orders today / revenue / top-selling items | Retrieve order activity for a period | `period`, `top_n`, `orders`, `revenue`, `top_items` (`product_id`, `name`, `quantity`) | Report order count and revenue for the period; list `top_items` only if the user asked for best sellers or top items. |
| What's the menu board showing / is the board simplified | Retrieve current menu-board mode | `mode` (`full`\|`simplified`), `reason`, `updated_at` | State the current mode, and the reason/when it last changed if available (fields may be `None` if it has never changed). |
| What the service/tool contract supports | Describe the service's current contract | `service`, `store_id`, `event_types`, `read_tools`, `act_tools` (and gate) | Use only to answer meta-questions about capabilities; never to answer a data question. |
| Any other kiosk queue/order/board analysis | Best compatible read capability from the current contract | all relevant returned fields | Call the smallest set of tools needed, reason over the returned data only, and state missing evidence instead of guessing. |

## Complex Questions

For trends, likely causes, or open-ended questions, call the relevant
capability above once each. Use only fields present in the response and state
missing evidence instead of guessing. A single `get_queue_depth` snapshot does
not prove a historical trend — use `get_queue_history` for that.

## Board Actions

`set_board_mode` simplifies (`mode="simplified"`) or restores (`mode="full"`)
the kiosk's on-screen menu board. It is policy-gated **automatic**: it is
rate-limited (20 calls per 60 seconds) but executes immediately and does
**not** wait for human approval — unlike Suspicious Activity's `open_case`.

1. Call `get_queue_depth` and/or `get_board_state` first to confirm the
   current depth/status and current board mode.
2. Only call `set_board_mode` when the user asks to simplify/restore the
   board, or when acting on a clear, stated condition the user asked you to
   act on (e.g. "simplify the board whenever the queue is HIGH").
3. Pass a short `reason` describing why (e.g. the queue depth/status that
   triggered it).
4. Report the result fields returned (`executed`, `level`, and `result` or
   `reason`) — if `executed` is false, state the reason rather than implying
   the board changed.
5. A diagnostic question about queue depth or the board never by itself
   authorizes calling `set_board_mode`.

## Service Unavailable

If a call to `smart-kiosk` fails or the server cannot be reached, say that
service is unavailable and answer only the portions of the question that
other successful tool results support. Never substitute a remembered or
invented number, and never assume a board-mode change succeeded without a
tool result confirming it.

## Owner Extension

Service owners should add specialized question mappings to the Capability
Routing table. Follow
[`../../docs/adding-a-service.md`](../../docs/adding-a-service.md) and keep
live values out of this file.
