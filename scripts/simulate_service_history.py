#!/usr/bin/env python3
"""Generate SYNTHETIC kiosk, weather and order-accuracy event -> operator-response records.

Same journal format as scripts/simulate_kiosk_history.py (``source: "simulated"``, ids
prefixed ``sim-``); the kiosk file is left untouched and ids never collide with it, so
every file can be imported into the one shared journal. Nothing here calls a service or
executes an action; the records are written to a file only.

Hidden operator policy (never shown to Hermes) plus noise. Item ids, event fields and context
shapes match the smart-kiosk-assistant and Order Accuracy (take-away, dine-in) MCP services:

  weather  W1 rain or cold (<= 11 C)    -> cold drinks off (DRINK-004 Cold Coffee, DRINK-005 Fresh Lime Soda)
           W2 hot spell (>= 28 C)       -> soft serve on (DESSERT-002, off in the morning)
           W3 rain stops                -> cold drinks back on
           W4 mild dry drift            -> no response
           W5 one rejected proposal and one inconsistent one-off (noise)
  accuracy A1 take-away order missing items -> remake the order
           A2 dine-in order missing items   -> no remake; a runner takes the item to the table
           A3 take-away order with only extra items -> ignore
           A4 dine-in order with a low accuracy score -> operator checks the camera first

Usage:
  python scripts/simulate_service_history.py [--days 8] [--seed 7] [--out FILE]
  python scripts/learn.py import learning/simulated/event_op_response.jsonl   # test journal only

The default output holds ALL stimulation scenarios (kiosk, weather, accuracy) in one file; the kiosk
scenarios come from scripts/simulate_kiosk_history.py, which is reused unchanged.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "scripts"))

import simulate_kiosk_history  # noqa: E402
from autonomy.learning import new_record  # noqa: E402

MENU = [("DRINK-001", "Pepsi (330 ml)", "beverages", 59.0), ("DRINK-003", "Mango Lassi (300 ml)", "beverages", 89.0),
        ("DRINK-004", "Cold Coffee (300 ml)", "beverages", 99.0),
        ("DRINK-005", "Fresh Lime Soda (300 ml)", "beverages", 69.0),
        ("DESSERT-001", "Chocolate Brownie", "desserts", 89.0), ("DESSERT-002", "Vanilla Soft Serve", "desserts", 59.0)]
COLD_DRINKS = ("DRINK-004", "DRINK-005")
SOFT_SERVE = "DESSERT-002"
COLD_OFF = [{"item_id": item_id, "available": False, "reason": "cold or wet weather"} for item_id in COLD_DRINKS]
COLD_ON = [{"item_id": item_id, "available": True, "reason": "weather back to normal"} for item_id in COLD_DRINKS]
SOFT_ON = [{"item_id": SOFT_SERVE, "available": True, "reason": "hot weather"}]
SAY = {
    "cold_off": ["rain's here, take cold coffee and lime soda off", "pull the cold drinks, nobody wants them now",
                 "cold drinks off till it dries up"],
    "cold_on": ["rain's gone, cold drinks back on", "put cold coffee and lime soda back",
                "dry again, normal drinks menu"],
    "soft_on": ["it's hot, switch the soft serve on", "soft serve on, heatwave", "turn the soft serve on, it's boiling"],
}


def weather_record(seq: int, seed: int, when: datetime, previous: dict, current: dict, kind: str,
                   changes: list[dict] | None, text: str, cold_on: bool, soft_on: bool,
                   proposed_status: str | None = None) -> dict:
    event_id = f"sim-weather-{seed}-{seq:05d}"
    event = {
        "event_id": event_id, "type": "weather_changed", "service": "weather",
        "occurred_at": when.isoformat(),
        "payload": {**current, "source": "synthetic", "simulated": True, "previous": previous},
    }
    items = [{"id": item_id, "name": name, "category": category, "price": price,
              "available": cold_on if item_id in COLD_DRINKS else soft_on if item_id == SOFT_SERVE else True}
             for item_id, name, category, price in MENU]
    context = {
        "kiosk.get_kiosk_context": {"menu": {"items": items}},
        "weather.get_weather_details": {k: current[k] for k in ("condition", "is_raining", "temperature_c")},
    }
    call = {"tool": "kiosk.change_menu_items",
            "arguments": {"changes": changes, "reason": text}} if changes else None
    proposed = {"tool": call["tool"], "arguments": call["arguments"], "summary": "synthetic proposal",
                "status": proposed_status} if call and kind in ("approved", "rejected") else None
    return new_record(
        source="simulated", event=event, kind=kind, text=text,
        tool_calls=[call] if call and kind == "instruction" else [], proposed=proposed,
        context=context, link="generated", record_id=event_id,
        ts=(when + timedelta(minutes=random.Random(seq).randint(1, 3))).isoformat(),
    )


def simulate_weather(days: int, seed: int, start: datetime) -> list[dict]:
    rng = random.Random(seed)
    records: list[dict] = []
    seq = 0

    def emit(when, previous, current, kind, changes, text, cold_on, soft_on, status=None):
        nonlocal seq
        seq += 1
        records.append(weather_record(seq, seed, when, previous, current, kind, changes, text,
                                      cold_on, soft_on, status))

    def state(raining: bool, temp: float) -> dict:
        return {"condition": "rain" if raining else "clear", "is_raining": raining, "temperature_c": temp,
                "precipitation_mm": round(rng.uniform(0.5, 4), 1) if raining else 0.0}

    for day in range(days):
        clock = start + timedelta(days=day, hours=9)
        cold_on, soft_on = True, False
        previous = state(False, rng.randint(15, 22))
        # W4: dry drift, nobody reacts.
        for _ in range(2):
            current = state(False, previous["temperature_c"] + rng.choice([-2, -1, 1, 2]))
            clock += timedelta(minutes=40)
            emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
                 "none", None, "", cold_on, soft_on)
            previous = current
        # W1: rain starts (or a cold snap), operator takes cold drinks off; one missed in ten.
        raining = rng.random() < 0.8
        current = state(raining, rng.randint(6, 11) if not raining else rng.randint(7, 16))
        clock += timedelta(hours=1)
        missed = rng.random() < 0.1
        emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
             "none" if missed else "instruction", None if missed else COLD_OFF,
             "" if missed else rng.choice(SAY["cold_off"]), cold_on, soft_on)
        cold_on = missed
        previous = current
        # Already off: temperature wobbles while it keeps raining; no response needed.
        if previous["is_raining"]:
            current = state(True, previous["temperature_c"] + rng.choice([-1, 1]))
            clock += timedelta(minutes=30)
            emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
                 "none", None, "", cold_on, soft_on)
            previous = current
        # W3: rain stops, cold drinks back on.
        current = state(False, rng.randint(13, 22))
        clock += timedelta(hours=2)
        emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
             "none" if cold_on else "instruction", None if cold_on else COLD_ON,
             "" if cold_on else rng.choice(SAY["cold_on"]), cold_on, soft_on)
        cold_on = True
        previous = current
        # W2: hot spell, operator switches the soft serve on.
        current = state(False, rng.randint(28, 35))
        clock += timedelta(hours=3)
        emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
             "instruction", SOFT_ON, rng.choice(SAY["soft_on"]), cold_on, soft_on)
        soft_on = True
    # W5: negative evidence. The agent proposed soft serve in mild weather and the operator rejected it
    # (approved proposals carry their execution status, the only recorded outcome), then one inconsistent one-off.
    base = start + timedelta(days=days, hours=11)
    mild = state(False, 24)
    emit(base, {"condition": "clear", "is_raining": False, "temperature_c": 22}, mild, "rejected", SOFT_ON,
         "not hot enough for soft serve", True, False, "rejected")
    emit(base + timedelta(hours=1), {"condition": "clear", "is_raining": False, "temperature_c": 24},
         state(False, 29), "approved", SOFT_ON, "", True, False, "executed")
    emit(base + timedelta(hours=2), {"condition": "clear", "is_raining": False, "temperature_c": 29},
         state(False, 20), "instruction", COLD_OFF[:1], "cold coffee off while the machine is cleaned", True, True)
    return records


TAKE_AWAY_ITEMS = ["french fries", "coke", "veg burger", "chicken nuggets", "ketchup", "apple pie"]
DINE_IN_ITEMS = ["garlic naan", "dal makhani", "jeera rice", "raita", "paneer tikka", "lassi"]


def accuracy_event(seq: int, seed: int, when: datetime, venue: str, missing: list[str], extra: list[str],
                   score: float, rng: random.Random) -> dict:
    """An order_mismatch_detected event as the take-away or dine-in Order Accuracy service sends it."""
    event_id = f"sim-accuracy-{seed}-{seq:05d}"
    order_id = f"SIM-{1000 + seq}"
    reason = ",".join(part for part in (f"missing:{len(missing)}" if missing else "",
                                        f"extra:{len(extra)}" if extra else "") if part)
    missing_items = [{"name": name, "quantity": 1} for name in missing]
    extra_items = [{"name": name, "quantity": 1} for name in extra]
    if venue == "take-away":
        payload = {"order_id": order_id, "station": "station_1", "run_number": 1, "num_frames": 3,
                   "inference_time_sec": round(rng.uniform(15, 40), 2), "missing_items": missing_items,
                   "extra_items": extra_items, "quantity_mismatch": [], "reason": reason,
                   "source": "order_accuracy", "source_event_type": "order_failed",
                   "ref_id": f"station_1:{order_id}:1"}
    else:
        image_id = f"{order_id}-img"
        payload = {"order_id": order_id, "station": f"table_{rng.randint(1, 12)}", "image_id": image_id,
                   "accuracy_score": score, "missing_items": missing_items, "extra_items": extra_items,
                   "quantity_mismatches": [], "reason": reason, "source": "order_accuracy_dine_in",
                   "source_event_type": "order_failed", "ref_id": f"{order_id}:{image_id}"}
    return {
        "event_id": event_id, "type": "order_mismatch_detected", "service": "accuracy", "occurred_at": when.isoformat(),
        "payload": {**payload, "venue": venue, "simulated": True},
    }


def accuracy_context(event: dict, flagged: int) -> dict:
    """The merged take-away + dine-in get_order_accuracy_context snapshot the agent reads."""
    payload = event["payload"]
    issues = ([{**item, "type": "missing_item"} for item in payload["missing_items"]]
              + [{**item, "type": "extra_item"} for item in payload["extra_items"]])
    observed = flagged + 6
    return {"accuracy.get_order_accuracy_context": {
        "summary": {"window_minutes": 30, "orders_observed": observed, "orders_accurate": observed - flagged,
                    "orders_flagged": flagged, "accuracy_rate": round((observed - flagged) / observed, 3)},
        "recent_orders": [{"order_id": payload["order_id"], "station_id": payload["station"], "result": "flagged",
                           "issues": issues, "venue": payload["venue"].replace("-", "_")}],
    }}


def simulate_accuracy(days: int, seed: int, start: datetime) -> list[dict]:
    rng = random.Random(seed + 1)
    records: list[dict] = []
    seq = 0
    scenarios = (["a1", "a1", "a2", "a3"]) * days
    scenarios += ["a4", "a4", "a2r", "a1r"]
    rng.shuffle(scenarios)
    for index, scenario in enumerate(scenarios):
        seq += 1
        when = start + timedelta(days=index // 4, hours=11 + (index % 4) * 2, minutes=rng.randint(0, 50))
        if scenario in ("a1", "a1r"):
            event = accuracy_event(seq, seed, when, "take-away", rng.sample(TAKE_AWAY_ITEMS, rng.choice([1, 1, 2])),
                                   [], 0.0, rng)
        elif scenario in ("a2", "a2r"):
            event = accuracy_event(seq, seed, when, "dine-in", rng.sample(DINE_IN_ITEMS, rng.choice([1, 1, 2])),
                                   [], round(rng.uniform(0.55, 0.85), 2), rng)
        elif scenario == "a3":
            event = accuracy_event(seq, seed, when, "take-away", [], rng.sample(TAKE_AWAY_ITEMS, 1), 0.0, rng)
        else:
            event = accuracy_event(seq, seed, when, "dine-in", rng.sample(DINE_IN_ITEMS, 1), [],
                                   round(rng.uniform(0.2, 0.45), 2), rng)
        order_id = event["payload"]["order_id"]
        context = accuracy_context(event, rng.randint(1, 3))
        remake = {"tool": "accuracy.request_remake",
                  "arguments": {"order_id": order_id, "reason": event["payload"]["reason"]}}
        proposal = {**remake, "summary": "synthetic proposal", "status": "proposed"}
        common = dict(source="simulated", event=event, context=context, link="generated",
                      record_id=event["event_id"], ts=(when + timedelta(minutes=2)).isoformat())
        if scenario == "a1":
            records.append(new_record(kind="instruction", text="remake it, the customer is waiting at the counter",
                                      tool_calls=[remake], **common))
        elif scenario == "a1r":
            # The agent proposed the remake and the operator approved it; status records the outcome.
            records.append(new_record(kind="approved", proposed={**proposal, "status": "executed"}, **common))
        elif scenario == "a2":
            # A runner is not a registered tool, so a live chat record carries text but no tool_calls.
            item = event["payload"]["missing_items"][0]["name"]
            records.append(new_record(kind="instruction", text=f"send a runner with the {item} to the table",
                                      **common))
        elif scenario == "a2r":
            records.append(new_record(kind="rejected", text="dine-in: a runner takes the missing item to the table",
                                      proposed=proposal, **common))
        elif scenario == "a3":
            records.append(new_record(kind="none", **common))
        else:
            records.append(new_record(kind="none", text="check the camera before deciding", **common))
    return records


def simulate_all(days: int, seed: int, start: datetime) -> list[dict]:
    """Kiosk, weather and accuracy stimulation records; ids are service-prefixed, hence unique."""
    records = (simulate_kiosk_history.simulate(days, seed, start) + simulate_weather(days, seed, start)
               + simulate_accuracy(days, seed, start))
    if len({record["id"] for record in records}) != len(records):
        raise ValueError("duplicate record ids in generated dataset")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--start", default="2026-09-01", help="first simulated day (YYYY-MM-DD, UTC)")
    parser.add_argument("--out", type=Path, default=ROOT / "learning/simulated/event_op_response.jsonl")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    records = simulate_all(args.days, args.seed, start)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
                        encoding="utf-8")
    print(f"Wrote {len(records)} synthetic records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
