---
name: order-accuracy
description: "Answer order accuracy, rework-rate, order-history, and station-totals questions for the Take-away and Dine-in Order Accuracy MCP services."
version: 3.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Order-Accuracy, Take-away, Dine-in, Rework-Rate, Station]
---

# Order Accuracy

Use the Order Accuracy MCP services as the only source of live accuracy facts.
Never answer from memory or an earlier turn when a fresh tool call is
available.

Order Accuracy currently exposes two separate deployments — one per venue
format — registered as distinct MCP servers:

* `order-accuracy-take-away` — the Take-away application.
* `order-accuracy-dine-in` — the Dine-in application.

## Contract Discovery

Before the first order-accuracy tool call in a conversation for a given
service, call `describe`. Use the returned contract to identify the current
read tools, input schemas, and event types for that service — Order Accuracy
is sensor-only, so `describe` should report no action tools; if it ever does,
treat that as a live signal and re-derive routing from it rather than from
this file. Do not use `describe` as evidence for live accuracy facts.

Map each request to the required capability below, then choose the compatible
tool from `describe`. If no compatible tool is available, explain that the
service contract does not support the request rather than guessing.

Always call the service that matches the venue format implied by the question
(e.g. "take-away order" → `order-accuracy-take-away`; "dine-in"/table/station
"T1"/"T2" → `order-accuracy-dine-in`). If the venue format is not stated and
both services are registered, ask which one, or call both and label each
result by service.

If a question implies taking an action (remake, comp, alert dismissal), check
`describe` first; if no compatible action tool is available, explain that
Order Accuracy can only report data and does not support that action.

## Capability Routing

| User intent or question | Required capability | Fields to use | Answer rule |
|---|---|---|---|
| Current or comparative rework/reject rate | Retrieve the rework rate for a period, optionally filtered by station, compared against a baseline period | period, station, orders seen, orders failed, rework rate, baseline period, baseline rework rate, baseline orders seen, delta vs. baseline | Report the rate as a percentage for the requested period; include the baseline comparison and delta only if the user asked for or implied a comparison. |
| Recent order validation history / recent mismatches | Retrieve order validation history (validated/failed events), oldest first | event type, status, order id, station, timestamp, accuracy score, missing items, extra items, quantity mismatches, reason | List orders in the order returned; state validated vs. failed and the reason for each failure. Do not invent an order that isn't in the result. |
| Pass/fail totals by station | Retrieve per-station pass/fail totals and rework rate | station (if provided), validated, failed, total, rework rate | Report validated/failed counts per station; call once per named station if the user asks about specific stations (e.g. T1 and T2), or once with no station filter for an all-station breakdown. |
| What the service/tool contract supports | Describe the service's current contract | service, store id, event types, read tools (and action tools, if any) | Use only to answer meta-questions about capabilities; never to answer a data question. |
| Any other order-accuracy analysis | Best compatible read capability from the current contract | all relevant returned fields | Call the smallest set of tools needed, reason over the returned data only, and state missing evidence instead of guessing. |

## Complex Questions

For trends, likely causes, or open-ended questions, call the relevant
capability above once each. Use only fields present in the response and state
missing evidence instead of guessing. A single snapshot does not prove a
historical trend unless the service returns multiple periods (the rework-rate
capability does, via its baseline period).

## Service Unavailable

If a call to `order-accuracy-take-away` or `order-accuracy-dine-in` fails or
the server cannot be reached, say that service is unavailable and answer only
the portions of the question supported by the other service or by other
successful tool results. Never substitute a remembered or invented number.

## Owner Extension

Service owners should add specialized question mappings to the Tool Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md)
and keep live values out of this file.
