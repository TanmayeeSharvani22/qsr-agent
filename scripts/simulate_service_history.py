#!/usr/bin/env python3
"""Generate SYNTHETIC kiosk, weather and order-accuracy event -> operator-response records.

Same journal format as scripts/simulate_kiosk_history.py (``source: "simulated"``, ids
prefixed ``sim-``); the kiosk file is left untouched and ids never collide with it, so
every file can be imported into the one shared journal. Nothing here calls a service or
executes an action; the records are written to a file only.

Hidden operator policy (never shown to Hermes) plus noise:

  weather  W1 rain or cold (<= 11 C)    -> hot drinks on the menu
           W2 hot spell (>= 28 C)       -> shakes on the menu
           W3 rain stops                -> hot drinks off again
           W4 mild dry drift            -> no response
           W5 one rejected proposal and one inconsistent one-off (noise)
  accuracy A1 missing item, confidence >= 0.9, pickup counter -> remake the order
           A2 confidence < 0.8                                 -> ignore (camera unsure)
           A3 wrong item at the drive-through                  -> comp (typed, no registered tool)
           A4 unclear case                                     -> operator wants to look first

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

MENU = [("hot-chocolate", "Hot Chocolate"), ("tea", "Tea"), ("shake", "Vanilla Shake")]
HOT_ON = [{"item_id": "hot-chocolate", "available": True, "reason": "cold or wet weather"},
          {"item_id": "tea", "available": True, "reason": "cold or wet weather"}]
HOT_OFF = [{"item_id": "hot-chocolate", "available": False, "reason": "weather back to normal"},
           {"item_id": "tea", "available": False, "reason": "weather back to normal"}]
SHAKE_ON = [{"item_id": "shake", "available": True, "reason": "hot weather"}]
SAY = {
    "hot_on": ["put hot chocolate and tea on the menu, it's miserable out", "hot drinks on please",
               "bring back hot chocolate and tea, people want them"],
    "hot_off": ["rain's gone, hot drinks back off", "take hot chocolate and tea off again",
                "back to normal menu now it's dry"],
    "shake_on": ["it's hot, put the vanilla shake on", "shakes on, heatwave", "turn the shake back on, it's boiling"],
}


def weather_record(seq: int, seed: int, when: datetime, previous: dict, current: dict, kind: str,
                   changes: list[dict] | None, text: str, hot_on: bool, shake_on: bool,
                   proposed_status: str | None = None) -> dict:
    event_id = f"sim-weather-{seed}-{seq:05d}"
    event = {
        "event_id": event_id, "type": "weather_changed", "service": "weather",
        "occurred_at": when.isoformat(),
        "payload": {**current, "source": "synthetic", "simulated": True, "previous": previous},
    }
    items = [{"id": item_id, "name": name,
              "available": hot_on if item_id != "shake" else shake_on} for item_id, name in MENU]
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

    def emit(when, previous, current, kind, changes, text, hot_on, shake_on, status=None):
        nonlocal seq
        seq += 1
        records.append(weather_record(seq, seed, when, previous, current, kind, changes, text,
                                      hot_on, shake_on, status))

    def state(raining: bool, temp: float) -> dict:
        return {"condition": "rain" if raining else "clear", "is_raining": raining, "temperature_c": temp,
                "precipitation_mm": round(rng.uniform(0.5, 4), 1) if raining else 0.0}

    for day in range(days):
        clock = start + timedelta(days=day, hours=9)
        hot_on = shake_on = False
        previous = state(False, rng.randint(15, 22))
        # W4: dry drift, nobody reacts.
        for _ in range(2):
            current = state(False, previous["temperature_c"] + rng.choice([-2, -1, 1, 2]))
            clock += timedelta(minutes=40)
            emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
                 "none", None, "", hot_on, shake_on)
            previous = current
        # W1: rain starts (or a cold snap), operator brings hot drinks on; one missed in ten.
        raining = rng.random() < 0.8
        current = state(raining, rng.randint(6, 11) if not raining else rng.randint(7, 16))
        clock += timedelta(hours=1)
        missed = rng.random() < 0.1
        emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
             "none" if missed else "instruction", None if missed else HOT_ON,
             "" if missed else rng.choice(SAY["hot_on"]), hot_on, shake_on)
        hot_on = hot_on or not missed
        previous = current
        # Already on: temperature wobbles while it keeps raining; no response needed.
        if previous["is_raining"]:
            current = state(True, previous["temperature_c"] + rng.choice([-1, 1]))
            clock += timedelta(minutes=30)
            emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
                 "none", None, "", hot_on, shake_on)
            previous = current
        # W3: rain stops, hot drinks off.
        current = state(False, rng.randint(13, 22))
        clock += timedelta(hours=2)
        emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
             "instruction" if hot_on else "none", HOT_OFF if hot_on else None,
             rng.choice(SAY["hot_off"]) if hot_on else "", hot_on, shake_on)
        hot_on = False
        previous = current
        # W2: hot spell, operator turns shakes on.
        current = state(False, rng.randint(28, 35))
        clock += timedelta(hours=3)
        emit(clock, {k: previous[k] for k in ("condition", "is_raining", "temperature_c")}, current,
             "instruction", SHAKE_ON, rng.choice(SAY["shake_on"]), hot_on, shake_on)
        shake_on = True
    # W5: negative evidence. The agent proposed shakes in mild weather and the operator rejected it
    # (approved proposals carry their execution status, the only recorded outcome), then one inconsistent one-off.
    base = start + timedelta(days=days, hours=11)
    mild = state(False, 24)
    emit(base, {"condition": "clear", "is_raining": False, "temperature_c": 22}, mild, "rejected", SHAKE_ON,
         "not hot enough for shakes", False, False, "rejected")
    emit(base + timedelta(hours=1), {"condition": "clear", "is_raining": False, "temperature_c": 24},
         state(False, 29), "approved", SHAKE_ON, "", False, False, "executed")
    emit(base + timedelta(hours=2), {"condition": "clear", "is_raining": False, "temperature_c": 29},
         state(False, 20), "instruction", HOT_ON, "tea on for the staff tasting", False, True)
    return records


def accuracy_event(seq: int, seed: int, when: datetime, issue: str, confidence: float, station: str) -> dict:
    event_id = f"sim-accuracy-{seed}-{seq:05d}"
    return {
        "event_id": event_id, "type": "order_mismatch_detected", "service": "accuracy", "occurred_at": when.isoformat(),
        "payload": {"order_id": f"SIM-{1000 + seq}", "station_id": "station-1" if station == "pickup_counter"
                    else "station-2", "station_type": station, "issue_type": issue, "confidence": confidence,
                    "simulated": True},
    }


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
            event = accuracy_event(seq, seed, when, "missing_item", round(rng.uniform(0.9, 0.98), 2), "pickup_counter")
        elif scenario in ("a2", "a2r"):
            event = accuracy_event(seq, seed, when, rng.choice(["missing_item", "wrong_item"]),
                                   round(rng.uniform(0.55, 0.79), 2), rng.choice(["pickup_counter", "drive_through"]))
        elif scenario == "a3":
            event = accuracy_event(seq, seed, when, "wrong_item", round(rng.uniform(0.85, 0.95), 2), "drive_through")
        else:
            event = accuracy_event(seq, seed, when, "missing_item", round(rng.uniform(0.8, 0.89), 2), "drive_through")
        order_id = event["payload"]["order_id"]
        context = {"accuracy.get_order_accuracy_context": {"summary": {"window_minutes": 30, "accuracy_rate": 0.875},
                                                          "alerts": []}}
        remake = {"tool": "accuracy.request_remake",
                  "arguments": {"order_id": order_id, "reason": "missing item confirmed"}}
        proposal = {**remake, "summary": "synthetic proposal", "status": "proposed"}
        common = dict(source="simulated", event=event, context=context, link="generated",
                      record_id=event["event_id"], ts=(when + timedelta(minutes=2)).isoformat())
        if scenario == "a1":
            records.append(new_record(kind="instruction", text="just remake the order, it's missing an item",
                                      tool_calls=[remake], **common))
        elif scenario == "a1r":
            # The agent proposed the remake and the operator approved it; status records the outcome.
            records.append(new_record(kind="approved", proposed={**proposal, "status": "executed"}, **common))
        elif scenario == "a2":
            records.append(new_record(kind="none", **common))
        elif scenario == "a2r":
            records.append(new_record(kind="rejected", text="camera is unsure, ignore", proposed=proposal, **common))
        elif scenario == "a3":
            # Comp has no registered autonomy tool, so a live chat record carries text but no tool_calls.
            records.append(new_record(kind="instruction", text="car's gone, comp them", **common))
        else:
            records.append(new_record(kind="none", text="need to check the camera before deciding", **common))
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
