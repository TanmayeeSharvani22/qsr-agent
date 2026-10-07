---
name: suspicious-activity
description: "Answer kitchen food-safety and suspicious-activity questions using SAD MCP read tools for zones, events, time ranges, frame references, counts, and station/shift trends."
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

## Contract Discovery

The SAD tools are already registered with their schemas; route requests with the
table below and call the data tool directly. Call `describe` only when the
operator asks what the service offers. `describe` returns service metadata, not
live food-safety evidence.

If no tool below fits the request, explain that the service contract does not
support it rather than guessing.

This is a read-only sensor service. It exposes `describe` and read tools only;
there are no SAD MCP tools for notifying operators, opening cases, or changing
runtime state. Do not claim to perform those actions through SAD.

## Capability Routing

| User intent or question | Required capability | Fields to use | Answer rule |
|---|---|---|---|
| Which zones are configured | `Get_all_zones` | returned zone list | List the zones exactly as returned; this is configured-zone data, not proof of activity. |
| All or recent events | `Get_all_activities` | `event_name`, `zone`, `pose`, `severity`, `description`, `timestamp`, `ref_id` | Report facts from returned records; distinguish a list from an aggregate count. |
| Events in a zone | `Get_activity_by_zone` or `Get_activity_by_zone_timestamp` | `zone`; optional `start_time`, `end_time` | Preserve the requested zone and time bounds. |
| Individual dropped-and-returned / floor-pickup incidents | `Search_retrospective_frames` | `zone="kitchen-prep"`, `event_name="food_safety_violation"`, `use_case="kitchen"`; optional time bounds | Use structured filters and omit `query` unless a single distinctive keyword is needed. List each returned event separately when requested; do not substitute a count-only tool. |
| Count matching incidents | `Get_event_count` | optional `zone`, `event_name`, `use_case`, time bounds, `minimum_severity` | Use only when the operator asks for a count. State explicit time bounds only when the operator provided them; otherwise say the count is across the current SAD log. |
| How often / which station and shift | `Get_trend_counts` | optional `zone`, `event_name`, `use_case`, time bounds | Report returned station/shift buckets only. State explicit time bounds only when the operator provided them; otherwise say the buckets are across the current SAD log. This tool counts events; it does not compare against a baseline. |
| Last N days / per-day counts / daily trend | `Get_daily_counts` | `days` (default 7); optional `zone`, `event_name`, `use_case` | Do not compute dates, sums, or trends yourself. For each zone, report its returned `summary` (total, every listed day with events, and `trend`). Never report a single day's count as the window total. |
| Severity threshold count | `Get_event_count` | `minimum_severity` | `minimum_severity="high"` includes both high and critical events. Do not describe it as an exact-severity count. |
| Frame evidence | `Search_retrospective_frames` | `frame`, `frame_refs`, `frame_count` | Each record is one event; show one row per `ref_id`, never one row per frame. `frame_refs` holds one sample reference and `frame_count` the total stored. If empty, say no frame reference was returned; do not claim an image was fetched or displayed. |

## Complex Questions

Prefer structured filters (`zone`, `event_name`, `use_case`, time range) over the
free-text `query` parameter. Phrases like "food area", "prep area", or "kitchen"
are not zone names; use `zone="kitchen-prep"` or omit `zone`. If a tool returns
an "Unknown ... Valid values" error, retry with a listed value instead of
reporting no records. The service's text search is literal and
conjunctive: every non-trivial word in `query` must appear verbatim in the stored
event, so a natural-language sentence (e.g. "object picked up from the floor")
usually matches nothing even when relevant events exist. Map the request to the
structured fields above and pass `query` only as a single distinctive keyword, or
omit it entirely.

For "today", calculate the date and time bounds in the configured `SAD_TIMEZONE`
and pass explicit ISO-8601 local times. If the requested date or time window is
ambiguous, ask a clarifying question instead of reusing an earlier interval.

For a list of incidents, call `Search_retrospective_frames` and report only the
records it returns. For a count-only question, call `Get_event_count`. For
station/shift grouping, call `Get_trend_counts`. For a combined request such as
"show anything dropped on the floor; how often and which station," use
`Get_trend_counts` for the frequency/station answer and `Search_retrospective_frames`
only if the operator also asks for individual records or frame evidence. Do not
answer a detailed list request with a count or carry counts forward from a
previous turn. Use only returned fields and keep each event's zone and severity
together. Copy `timestamp`, `severity`, and `description` verbatim; never
paraphrase, round, or fill them in. A single snapshot does not establish a trend or baseline comparison.
Never infer or announce a time window from the earliest and latest returned event;
only mention a `between ... and ...` window when the operator supplied that
window or you asked for and received clarification.

## Events and Actions

SAD may push eligible critical events to the configured QSR autonomy endpoint.
That is a separate event-delivery path, not an MCP action initiated during chat.
The QSR Autonomy Decisions panel shows the assessment status. SAD itself cannot
notify an operator or open a case through an MCP tool.

## Owner Extension

Service owners should add specialized question mappings to the Capability Routing
table. Follow [`../../docs/adding-a-service.md`](../../docs/adding-a-service.md)
and keep live values out of this file.
