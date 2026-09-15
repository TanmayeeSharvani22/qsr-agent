---
name: suspicious-activity
description: "Answer kitchen food-safety and suspicious-activity questions (zones, poses, severity, dropped-and-returned food, per-station frequency, time ranges) and safely route operator notifications and case creation through the suspicious-activity MCP service."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Food-Safety, Kitchen, Suspicious-Activity, SAD]
---

# Suspicious Activity (Kitchen Food Safety)

Use the suspicious-activity MCP service as the only source of suspicious-activity
and kitchen food-safety facts. Never answer from memory or an earlier turn when a
fresh tool call is available. Each event is one detected violation with a `zone`,
`pose`, `severity`, `camera_id`, `object_id`, `description`, and `ts_ms`.

## Tool Routing

| User intent or question | Tool | Fields to use | Answer rule |
|---|---|---|---|
| Which zones have activity | `Get_all_zones` | returned zone list | List the zones exactly as returned; do not invent zones. |
| All events / recent violations | `Get_all_activities` | `zone`, `pose`, `severity`, `description`, `ts_ms` | Summarize count first, then notable events; keep severity and zone with each. |
| Events in a specific zone | `Get_activity_by_zone` | `zone`, `pose`, `severity`, `description` | Filter to the named zone; state the count and severities present. |
| Dropped-and-returned food ("dropped on the floor and put back") | `Get_activity_by_zone` or `Get_all_activities` | `pose` = `item-drop-return`, `zone`, `camera_id` | Select only `item-drop-return` events; report how often and which station/zone/camera. |
| How often / which station | `Get_all_activities` | group by `zone` / `camera_id` | Count matching events per zone or camera; do not fabricate stations without evidence. |
| Events in a time range | `Get_activity_by_zone_timestamp` | `zone`, `start_ms`, `end_ms` | Preserve the epoch-ms bounds; state the window used and the count. |
| Severity questions (how many high) | `Get_activity_by_zone` or `Get_all_activities` | `severity` in {low, medium, high} | Count by the exact `severity` value; do not reinterpret severity. |
| Any other food-safety analysis | best-matching read tool | all relevant returned fields | Call once, reason over the result, show brief counts, and state missing evidence instead of guessing. |

## Complex Questions

For trends, per-station frequency, comparisons, or open-ended questions, call the
narrowest read tool that returns the needed events, then reason over that result.
Use only fields present in the response, keep each event's `zone` and `severity`
together, and distinguish observed facts from recommendations. A single snapshot
does not prove a historical trend unless multiple time points are returned.

## Notify Actions

`notify_operator` surfaces an event to the store operator. It is automatic and
rate-limited, but a diagnostic question never authorizes a notification.

1. Call a read tool to confirm the exact `zone` and the event being surfaced.
2. State the zone and the operator-facing message you will send.
3. Send only after the user asks to notify, or when acting on a clear
   high-severity food-safety violation the user asked you to act on.
4. Report `executed`, `gate`, and the returned result fields.
5. If `placeholder` is true, state that no real operator system was contacted.

## Case Actions

`open_case` opens a loss-prevention / food-safety investigation and is
policy-gated: it always requires explicit human approval.

1. Call a read tool to resolve the exact `zone`, `object_id`, and `severity`.
2. Present the evidence and the proposed case.
3. Obtain explicit user approval in the current conversation before calling.
4. Report `executed`, `gate`, and the reason if it was not executed.
5. Never infer approval from urgency or a prior approval.

## Owner Extension

Service owners should add specialized question mappings to the Tool Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md)
and keep live values out of this file.
