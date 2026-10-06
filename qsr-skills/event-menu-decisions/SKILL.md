---
name: event-menu-decisions
description: "Recommend bounded kiosk menu availability changes when weather or queue events arrive."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Autonomy, Weather, Queue, Menu]
---

# Event Menu Decisions

Decide whether a `weather_changed` or `queue_count_changed` event justifies a
temporary menu availability change. Treat event values as the newest observation;
use the supplied kiosk state for staffing, demand, wait time, and current menu.
Kiosk context contains no weather. When current weather matters, read
`weather.get_weather_details` (`condition`, `is_raining`, `temperature_c`,
`source`, `simulated`, `observed_at`) and keep it distinct from the event.

For rain or cold, consider warm drinks such as Hot Chocolate or Tea. For queue
pressure, consider queue depth, wait, staffing, demand, abandonment, and item
preparation effort. Restore hidden items when conditions recover. Recommend no
change when the current menu already fits or evidence is insufficient.

## Queue Recovery

For a queue event, assess its `queue_count` against `previous_queue_count` when
provided. A lower count can support restoring temporary queue restrictions.
If `temporarily_hidden_items` is provided, resolve those IDs against the live
menu and consider restoring the ones with `available: false`. Do not assume
that every unavailable item was hidden for queue pressure; stock or equipment
restrictions need separate evidence before restoration.

The event and kiosk snapshot are separate observations. A different snapshot
queue count must be acknowledged, not substituted for the reported recovery.
Rain or already-available warm drinks alone do not justify keeping a temporary
queue restriction. Explain any concrete evidence against restoration. Submit a
justified change as a pending proposal; lack of approval is not a no-action reason.

Hard constraints: use only exact live item IDs; availability only, never prices;
at most three changes; never repeat current availability; give each change a
brief evidence-based reason; recommendations require operator approval.