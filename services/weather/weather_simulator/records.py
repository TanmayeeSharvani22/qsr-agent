"""Normalized weather record shared by every provider.

Field names follow the `get_weather_details` output of the open-source
`mcp_weather_server` (Open-Meteo based), so the providers are interchangeable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

WMO_DESCRIPTIONS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

RAINING_CONDITIONS = frozenset({"drizzle", "rain", "storm"})


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float | None = None
    longitude: float | None = None


def condition_for_code(code: int) -> str:
    if code in (0, 1):
        return "clear"
    if code in (2, 3):
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if 95 <= code <= 99:
        return "storm"
    return "unknown"


def dew_point_c(temperature_c: float, relative_humidity_percent: float) -> float:
    # Magnus approximation.
    a, b = 17.62, 243.12
    gamma = math.log(max(relative_humidity_percent, 1.0) / 100.0) + a * temperature_c / (b + temperature_c)
    return round(b * gamma / (a - gamma), 1)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def normalize(record: dict[str, Any], *, source: str, simulated: bool) -> dict[str, Any]:
    """Add the provider-neutral fields every consumer may rely on."""
    code = int(record["weather_code"])
    condition = condition_for_code(code)
    rain_mm = record.get("rain_mm") or 0.0
    return {
        **record,
        "weather_description": WMO_DESCRIPTIONS.get(code, "Unknown weather condition"),
        "condition": condition,
        "is_raining": condition in RAINING_CONDITIONS or rain_mm > 0,
        "source": source,
        "simulated": simulated,
        "observed_at": record.get("observed_at") or utc_now(),
    }


def format_summary(record: dict[str, Any]) -> str:
    text = (
        f"The weather in {record['city']} is {record['weather_description']} with a "
        f"temperature of {record['temperature_c']}°C, relative humidity at "
        f"{record.get('relative_humidity_percent')}%. Wind is {record.get('wind_speed_kmh')} km/h "
        f"with gusts up to {record.get('wind_gusts_kmh')} km/h."
    )
    if record.get("snowfall_cm"):
        text += f" Snowfall of {record['snowfall_cm']} cm is occurring."
    elif record.get("rain_mm"):
        text += f" Rainfall of {record['rain_mm']} mm is occurring."
    if record.get("precipitation_probability_percent"):
        text += f" Precipitation probability is {record['precipitation_probability_percent']}%."
    text += f" Cloud cover is {record.get('cloud_cover_percent')}%."
    if record.get("simulated"):
        text += " (Simulated weather.)"
    return text
