---
name: loss-prevention
description: "Answer self-checkout loss-prevention, age-mix, and VLM item-recognition questions using Loss Prevention MCP read tools for loss history, scenario/lane filters, counts, lanes, age-range distribution, and inventory-matched items."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Loss-Prevention, Self-Checkout, Age-Mix, Signage]
---

# Loss Prevention (Self-Checkout)

Use the loss-prevention MCP service as the only source of self-checkout loss and
age-range facts. Never answer from memory or an earlier turn when a fresh tool
call is available.

- Each **loss event** has `scenario`, `lane`, `camera_id`, `severity`,
  `tracking_id`, `frame`, `description`, and `timestamp`.
- Each **age estimate** has `age_range`, `lane`, `camera_id`, `tracking_id`,
  `gender`, and `frame`. Age-range counts feed the signage-board decision.
- Each **item verification** (VLM workload) has `item_name`, `matched`, `lane`,
  and `camera_id`. `matched` = true means the item is in the store inventory list.

Loss `scenario` is one of: `items_in_basket`, `hidden_items`,
`fake_scan_detection`, `multi_product_identification`, `product_switching`,
`sweethearting`. Age ranges are `0-18`, `18-25`, `25-35`, `35-45`, `45-60`, `60+`.

## Contract Discovery

The loss-prevention tools are already registered with their schemas; route
requests with the table below and call the data tool directly. Call `describe`
only when the operator asks what the service offers; it returns service
metadata, not live evidence.

This is a read-only sensor service. It exposes `describe` and read tools only;
there are no tools to change state, open cases, or notify operators. Do not claim
to perform those actions.

## Capability Routing

| User intent or question | Required capability | Fields to use | Answer rule |
|---|---|---|---|
| Recent loss incidents / history | `Get_loss_history` | optional `scenario`, `lane`, `start_time`, `end_time`, `limit` | List returned events; keep `scenario`, `lane`, and `severity` with each. Distinguish a list from an aggregate count. |
| Incidents for one scenario or lane | `Get_loss_history` | `scenario` and/or `lane` | Use exact `scenario`/`lane` values; preserve any requested time bounds. |
| How many loss incidents | `Get_loss_event_count` | optional `scenario`, `lane`, `start_time`, `end_time` | Use only when the operator asks for a count. State explicit time bounds only when the operator provided them; otherwise say the count is across the current log. |
| Age mix / age distribution / signage decision | `Get_age_range_counts` | optional `start_time`, `end_time`, `lane` | Report the returned per-range counts as the age mix, worded as **detections** (for example "749 detections in 35-45"), never as people, customers, or shoppers: one person is detected many times. Proportions across ranges are meaningful; absolute counts are not headcounts. Do not compute ranges yourself; the counts are already bucketed. For "right now", "current", or "at the self-checkout", call with NO arguments: do not add a time window and do not pass a `lane`. "Self-checkout" is not a lane id. |
| Which lanes have activity | `Get_lanes` | returned lane list | List lanes exactly as returned; lanes come from loss activity. |
| Items recognized at checkout / unknown or non-inventory items | `Get_item_verifications` | optional `matched`, `lane`, `period`, `start_time`, `end_time`, `limit` | List `item_name` with matched/not matched. Use `matched=false` for "unknown", "not in inventory", or "unrecognized" items. |
| How many items matched inventory | `Get_item_verification_summary` | optional `lane`, `period`, `start_time`, `end_time` | Report `matched`, `unmatched`, and `unmatched_items`. These come only from VLM runs; an all-zero result means no VLM run has been ingested. |
| What the service offers | `describe` | service, event types, read tools | Use only for meta questions about capabilities, never as live evidence. |

## Complex Questions

Prefer the structured filters (`scenario`, `lane`, time range) over free text.
Use exact scenario names and lane ids (for example `lane-1`); phrases like
"register 1" or "checkout" are not lane ids. If a tool returns an
"Unknown ... Valid values" error, retry with a listed value instead of reporting
no records.

For "last hour", "today", or "last 24 hours", pass `period` (`last_hour`,
`today`, `last_24_hours`); the server computes the window from its own clock. Never
compute clock times yourself for relative windows. Use `start_time`/`end_time`
only for an explicit date or time the operator gives. If no window is given, say
the result is across the current log rather than inventing bounds.

Age-mix questions are about the proportion of age ranges present, not individual
identities. Report the distribution from `Get_age_range_counts`; a higher count
in a range means more detections in that range over the period, not distinct
people. Keep loss and age results separate; they are different event types.
If the operator asks "how many people", answer with the detection count and say
it is not a unique-visitor count; the service does not count distinct people.

Do not add a `lane` filter unless the operator names a specific lane id (for
example `lane-1`). Phrases like "right now", "current", or "self-checkout" are
not filters: answer them with no time or lane arguments across the current log.
An empty result after you added a filter usually means the filter was too
narrow - retry with no arguments before saying data is unavailable.

## Owner Extension

Service owners should add specialized mappings to the routing table above and
keep live values out of this file.
