---
name: order-accuracy
description: "Answer order accuracy, mismatch, station, confidence, flagged-order, and alert questions; safely route remake and comp actions through the order-accuracy MCP service."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Order-Accuracy, Mismatch, Station, Remake, Comp]
---

# Order Accuracy

Use the Order Accuracy MCP service as the only source of live accuracy facts.
Do not treat a model inference, remembered value, or kiosk result as accuracy
evidence.

## Tool Routing

| User intent or question | Tool | Fields to use | Answer rule |
|---|---|---|---|
| Current accuracy rate | `get_order_accuracy_context` | `summary.accuracy_rate`, `orders_accurate`, `orders_observed`, `window_minutes`, `observed_at` | Format rate as a percentage and include the fraction and time window. |
| Number of inaccurate or flagged orders | `get_order_accuracy_context` | `summary.orders_flagged`, `summary.orders_observed`, `window_minutes` | State flagged count separately from observed count. |
| Which station is performing poorly | `get_order_accuracy_context` | `stations`, `alerts` | Compare station counts without inventing station rates when denominators are absent. Include matching alert evidence. |
| What was wrong with an order | `get_order_accuracy_context` | matching `recent_orders[].expected_items`, `observed_items`, `issues` | Identify missing/wrong items and include confidence; do not claim certainty beyond the confidence value. |
| Recent mismatches or alerts | `get_order_accuracy_context` | `recent_orders`, `alerts` | Separate detected mismatches from service-generated alerts. |
| Any other order-accuracy analysis | `get_order_accuracy_context` | All returned fields relevant to the question | Call once, reason over the snapshot, show calculations briefly, and state missing evidence instead of guessing. |

## Complex Questions

For trends, likely causes, prioritization, station comparisons, or open-ended
questions, call `get_order_accuracy_context` once. Use only fields present in
the response, preserve the summary window, and distinguish observed facts from
recommendations. A snapshot does not prove a historical trend unless the
service returns multiple time periods.

## Remake Actions

A question about a mismatch does not authorize a remake.

1. Call `get_order_accuracy_context` and locate the exact `order_id` and issue.
2. Explain the evidence and proposed remake reason.
3. Obtain explicit user approval before calling `request_remake`.
4. Report `executed`, `gate`, `status`, and `action_id`.
5. If `placeholder` is true, state that no production line was notified.

## Comp Actions

`issue_comp` is policy-gated and always requires explicit human approval. Never
choose an amount that the user did not provide or approve. If execution is
denied, report the denial and do not retry. If `placeholder` is true, state that
no external payment or POS system was changed.

## Owner Extension

Service owners should add specialized question mappings to the Tool Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md)
and keep live values out of this file.