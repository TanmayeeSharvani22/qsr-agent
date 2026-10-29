#!/usr/bin/env python3
"""Generate simulated historic kiosk queue events with the operator's response.

The simulated operator follows a hidden policy (never shown to Hermes) plus
noise, and writes records in exactly the journal format live capture uses:

  K1  queue >= 10 or wait >= 8 min   -> express mode
  K2  wait >= 8 min and a kiosk idle -> open one more kiosk
  K3  queue >= 8                     -> upsell prompts off
  K4  queue < 5 twice in a row       -> back to baseline settings

Usage:
  python scripts/simulate_kiosk_history.py [--days 8] [--seed 7] [--out FILE]
  python scripts/learn.py import learning/simulated/kiosk-queue-history.jsonl
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

from autonomy.learning import new_record  # noqa: E402

BASELINE = {"kiosk_mode": "standard", "active_kiosks": 3, "upsell_enabled": True}
MAX_KIOSKS = 4
PHRASES = {
    "express": ["switch kiosks to express, skip customisation", "put the kiosks in express mode",
                "go express on the kiosks, no customising", "express mode please, line is long"],
    "open": ["open kiosk {n}", "open up kiosk {n}", "bring kiosk {n} online", "get kiosk {n} running"],
    "upsell": ["kill the 'add a drink?' screens, they slow the line", "turn off the upsell prompts",
               "no upsell screens right now", "drop the add-a-drink prompts"],
    "normal": ["ok, back to normal", "line's gone, back to normal settings", "we're fine now, reset the kiosks",
               "back to standard, upsell on"],
}
# Inconsistent one-offs the learner should ignore.
ONE_OFFS = [("open", "kiosk 4 on, testing the screen"), ("upsell", "upsell off for a bit, testing")]


def queue_curve(minute: int, rng: random.Random) -> int:
    """Queue length by minute of day: lunch and dinner rushes plus noise."""
    lunch = 13 * max(0.0, 1 - abs(minute - 765) / 75)
    dinner = 11 * max(0.0, 1 - abs(minute - 1125) / 70)
    return max(0, round(2 + lunch + dinner + rng.gauss(0, 1.5)))


def operator_response(queue: int, previous: int, wait: int, state: dict, rng: random.Random, allow_one_off: bool):
    """Hidden policy: return (text, changes) or None when the operator does nothing."""
    wanted: dict = {}
    parts: list[str] = []
    if queue >= 10 or wait >= 8:
        if state["kiosk_mode"] != "express":
            wanted["mode"] = "express"
            parts.append(rng.choice(PHRASES["express"]))
    if wait >= 8 and state["active_kiosks"] < MAX_KIOSKS:
        wanted["active_kiosks"] = state["active_kiosks"] + 1
        parts.append(rng.choice(PHRASES["open"]).format(n=state["active_kiosks"] + 1))
    if queue >= 8 and state["upsell_enabled"]:
        wanted["upsell_enabled"] = False
        parts.append(rng.choice(PHRASES["upsell"]))
    if queue < 5 and previous < 5 and state != BASELINE:
        settings = {"kiosk_mode": "mode", "active_kiosks": "active_kiosks", "upsell_enabled": "upsell_enabled"}
        wanted = {settings[key]: value for key, value in BASELINE.items() if state[key] != value}
        parts = [rng.choice(PHRASES["normal"])]
    if wanted and rng.random() < 0.1:
        return None  # operator missed it
    if not wanted and allow_one_off and queue <= 4 and rng.random() < 0.02:
        kind, text = rng.choice(ONE_OFFS)
        if kind == "open" and state["active_kiosks"] < MAX_KIOSKS:
            return text, {"active_kiosks": state["active_kiosks"] + 1}
        if kind == "upsell" and state["upsell_enabled"]:
            return text, {"upsell_enabled": False}
        return None
    return (" and ".join(parts), wanted) if wanted else None


def simulate(days: int, seed: int, start: datetime) -> list[dict]:
    rng = random.Random(seed)
    records: list[dict] = []
    counter = 0
    one_offs = 0
    for day in range(days):
        state = dict(BASELINE)
        previous = 2
        staff = rng.randint(6, 9)
        for minute in range(600, 1260, 10):
            queue = queue_curve(minute, rng)
            if queue == previous:
                continue
            counter += 1
            wait = max(0, round(queue * 0.75 + rng.gauss(0, 1)))
            occurred = start + timedelta(days=day, minutes=minute)
            response = operator_response(queue, previous, wait, state, rng, one_offs < 2)
            text, changes = response or ("", {})
            one_offs += text in {text for _kind, text in ONE_OFFS}
            event = {
                "event_id": f"sim-kiosk-{seed}-{counter:05d}", "type": "queue_count_changed",
                "service": "kiosk", "occurred_at": occurred.isoformat(),
                "payload": {"queue_count": queue, "previous_queue_count": previous,
                            "estimated_wait_minutes": wait},
            }
            operations = {**state, "queue_count": queue, "estimated_wait_minutes": wait,
                          "staff_on_duty": staff, "max_kiosks": MAX_KIOSKS, "baseline_settings": BASELINE}
            # Events the operator ignored are recorded too: they are the negative evidence.
            records.append(new_record(
                source="simulated", event=event, kind="instruction" if response else "none", text=text,
                tool_calls=[{"tool": "kiosk.update_kiosk_settings",
                             "arguments": {**changes, "reason": text}}] if response else [],
                context={"kiosk.get_kiosk_context": {"operations": operations}},
                link="generated", record_id=f"sim-kiosk-{seed}-{counter:05d}",
                ts=(occurred + timedelta(minutes=rng.randint(1, 3))).isoformat(),
            ))
            state.update({{"mode": "kiosk_mode"}.get(key, key): value for key, value in changes.items()})
            previous = queue
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--start", default="2026-09-01", help="first simulated day (YYYY-MM-DD, UTC)")
    parser.add_argument("--out", type=Path, default=ROOT / "learning/simulated/kiosk-queue-history.jsonl")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    records = simulate(args.days, args.seed, start)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
                        encoding="utf-8")
    print(f"Wrote {len(records)} simulated records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
