#!/usr/bin/env python3
"""Set the simulated kiosk queue and post a queue_count_changed event.

Usage (host):    .venv/mcp/bin/python scripts/queue_event.py --count 12 [--wait 9]
Usage (compose): make queue COUNT=12 [WAIT=9]

The kiosk placeholder's context reflects the new queue immediately; the event
carries ``service: kiosk`` so operator responses are learnt into learned-kiosk.
Leave QSR_QUEUE_COUNT / QSR_ESTIMATED_WAIT_MINUTES unset: they override this state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests/mcp-services"))

import kiosk_server  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, required=True, help="customers in the queue")
    parser.add_argument("--wait", type=int, help="estimated wait minutes (default: about 0.75 x count)")
    parser.add_argument("--url", default=os.environ.get("QSR_UI_URL", "http://127.0.0.1:8600"))
    parser.add_argument("--no-event", action="store_true", help="only update kiosk state")
    args = parser.parse_args()
    if args.count < 0 or (args.wait is not None and args.wait < 0):
        parser.error("count and wait must be nonnegative")
    wait = args.wait if args.wait is not None else round(args.count * 0.75)
    previous = kiosk_server.get_kiosk_context()["operations"]["queue_count"]
    kiosk_server.update_operations({"queue_count": args.count, "estimated_wait_minutes": wait})
    print(f"Kiosk queue {previous} -> {args.count}, wait {wait} min")
    if args.no_event:
        return 0
    event = {
        "event_id": f"queue-{uuid.uuid4().hex[:12]}",
        "event_type": "queue_count_changed",
        "service": "kiosk",
        "store_id": kiosk_server.STORE_ID,
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {"queue_count": args.count, "previous_queue_count": previous, "estimated_wait_minutes": wait},
    }
    request = urllib.request.Request(
        args.url.rstrip("/") + "/autonomy/events", data=json.dumps(event).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        print(response.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
