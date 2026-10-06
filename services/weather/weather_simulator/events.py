"""Publishes `weather_changed` events to a webhook such as QSR `/autonomy/events`."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

logger = logging.getLogger("weather-simulator")

EVENT_TYPE = "weather_changed"

# Returns the HTTP status code; raises OSError subclasses on transport failure.
PostJson = Callable[[str, bytes, dict[str, str], float], int]


def _post_json(url: str, body: bytes, headers: dict[str, str], timeout: float) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


class WeatherEventPublisher:
    def __init__(
        self,
        webhook_url: str | None,
        store_id: str,
        token: str | None = None,
        temperature_delta_c: float = 1.0,
        timeout: float = 5.0,
        attempts: int = 3,
        post_json: PostJson = _post_json,
    ) -> None:
        self.webhook_url = webhook_url
        self.store_id = store_id
        self.token = token
        self.temperature_delta_c = temperature_delta_c
        self.timeout = timeout
        self.attempts = attempts
        self._post_json = post_json

    def is_significant(self, previous: dict[str, Any], current: dict[str, Any]) -> bool:
        return (
            previous["condition"] != current["condition"]
            or previous["is_raining"] != current["is_raining"]
            or abs(current["temperature_c"] - previous["temperature_c"]) >= self.temperature_delta_c
        )

    def build_event(self, previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return {
            "event_id": f"weather-{self.store_id}-{stamp}-{uuid4().hex[:8]}",
            "event_type": EVENT_TYPE,
            "store_id": self.store_id,
            "occurred_at": current["observed_at"],
            "data": {
                "condition": current["condition"],
                "is_raining": current["is_raining"],
                "temperature_c": current["temperature_c"],
                "weather_code": current["weather_code"],
                "weather_description": current["weather_description"],
                "precipitation_mm": current.get("precipitation_mm"),
                "location": current["city"],
                "source": current["source"],
                "simulated": current["simulated"],
                "previous": {
                    "condition": previous["condition"],
                    "is_raining": previous["is_raining"],
                    "temperature_c": previous["temperature_c"],
                },
            },
        }

    def publish(
        self, previous: dict[str, Any], current: dict[str, Any], force: bool = False
    ) -> dict[str, Any]:
        if not self.webhook_url:
            return {"published": False, "reason": "WEATHER_EVENT_WEBHOOK_URL is not configured"}
        if not force and not self.is_significant(previous, current):
            return {"published": False, "reason": "change below event threshold"}
        event = self.build_event(previous, current)
        body = json.dumps(event).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        status = None
        for attempt in range(self.attempts):
            try:
                status = self._post_json(self.webhook_url, body, headers, self.timeout)
            except OSError as error:
                logger.warning("weather event delivery failed (attempt %d): %s", attempt + 1, error)
                status = None
            if status is not None and 200 <= status < 300:
                return {"published": True, "event_id": event["event_id"], "status": status}
            # Client errors other than throttling will not succeed on retry.
            if status is not None and 400 <= status < 500 and status != 429:
                break
            if attempt + 1 < self.attempts:
                time.sleep(0.5 * 2**attempt)
        return {
            "published": False,
            "event_id": event["event_id"],
            "status": status,
            "reason": "webhook delivery failed",
        }
