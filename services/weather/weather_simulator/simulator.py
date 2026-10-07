"""Operator-controlled weather backend for demos and tests."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, get_args

from .records import Location, dew_point_c, normalize, utc_now

Condition = Literal["clear", "cloudy", "fog", "drizzle", "rain", "storm", "snow"]
CONDITIONS: tuple[str, ...] = get_args(Condition)

MIN_TEMPERATURE_C = -60.0
MAX_TEMPERATURE_C = 60.0

# Representative observations per condition; temperature is overridable.
SCENARIOS: dict[str, dict[str, Any]] = {
    "clear": {
        "weather_code": 0, "temperature_c": 22.0, "relative_humidity_percent": 45,
        "wind_speed_kmh": 8.0, "wind_gusts_kmh": 15.0, "precipitation_mm": 0.0,
        "rain_mm": 0.0, "snowfall_cm": 0.0, "precipitation_probability_percent": 0,
        "cloud_cover_percent": 5, "pressure_hpa": 1018.0, "uv_index": 6.0, "visibility_m": 24000,
    },
    "cloudy": {
        "weather_code": 3, "temperature_c": 18.0, "relative_humidity_percent": 65,
        "wind_speed_kmh": 12.0, "wind_gusts_kmh": 22.0, "precipitation_mm": 0.0,
        "rain_mm": 0.0, "snowfall_cm": 0.0, "precipitation_probability_percent": 15,
        "cloud_cover_percent": 90, "pressure_hpa": 1012.0, "uv_index": 2.0, "visibility_m": 18000,
    },
    "fog": {
        "weather_code": 45, "temperature_c": 9.0, "relative_humidity_percent": 98,
        "wind_speed_kmh": 3.0, "wind_gusts_kmh": 6.0, "precipitation_mm": 0.0,
        "rain_mm": 0.0, "snowfall_cm": 0.0, "precipitation_probability_percent": 10,
        "cloud_cover_percent": 100, "pressure_hpa": 1015.0, "uv_index": 0.5, "visibility_m": 300,
    },
    "drizzle": {
        "weather_code": 53, "temperature_c": 15.0, "relative_humidity_percent": 88,
        "wind_speed_kmh": 10.0, "wind_gusts_kmh": 18.0, "precipitation_mm": 0.6,
        "rain_mm": 0.6, "snowfall_cm": 0.0, "precipitation_probability_percent": 70,
        "cloud_cover_percent": 100, "pressure_hpa": 1009.0, "uv_index": 1.0, "visibility_m": 9000,
    },
    "rain": {
        "weather_code": 63, "temperature_c": 14.0, "relative_humidity_percent": 92,
        "wind_speed_kmh": 18.0, "wind_gusts_kmh": 32.0, "precipitation_mm": 3.2,
        "rain_mm": 3.2, "snowfall_cm": 0.0, "precipitation_probability_percent": 90,
        "cloud_cover_percent": 100, "pressure_hpa": 1004.0, "uv_index": 0.5, "visibility_m": 6000,
    },
    "storm": {
        "weather_code": 95, "temperature_c": 16.0, "relative_humidity_percent": 95,
        "wind_speed_kmh": 45.0, "wind_gusts_kmh": 72.0, "precipitation_mm": 12.0,
        "rain_mm": 12.0, "snowfall_cm": 0.0, "precipitation_probability_percent": 100,
        "cloud_cover_percent": 100, "pressure_hpa": 996.0, "uv_index": 0.0, "visibility_m": 2500,
    },
    "snow": {
        "weather_code": 73, "temperature_c": -2.0, "relative_humidity_percent": 90,
        "wind_speed_kmh": 14.0, "wind_gusts_kmh": 25.0, "precipitation_mm": 1.5,
        "rain_mm": 0.0, "snowfall_cm": 1.5, "precipitation_probability_percent": 85,
        "cloud_cover_percent": 100, "pressure_hpa": 1008.0, "uv_index": 0.5, "visibility_m": 4000,
    },
}


def validate_condition(condition: str) -> str:
    if condition not in SCENARIOS:
        raise ValueError(f"unknown condition {condition!r}; expected one of: {', '.join(CONDITIONS)}")
    return condition


def validate_temperature(temperature_c: float | None) -> float | None:
    if temperature_c is None:
        return None
    if isinstance(temperature_c, bool) or not isinstance(temperature_c, (int, float)):
        raise ValueError("temperature_c must be a number")
    if not MIN_TEMPERATURE_C <= temperature_c <= MAX_TEMPERATURE_C:
        raise ValueError(f"temperature_c must be between {MIN_TEMPERATURE_C} and {MAX_TEMPERATURE_C}")
    return round(float(temperature_c), 1)


class SimulatedWeatherProvider:
    """Serves weather set by an operator, persisted so every process agrees."""

    name = "simulator"

    def __init__(
        self,
        state_path: Path,
        location: Location,
        default_condition: str = "clear",
        default_temperature_c: float | None = None,
    ) -> None:
        self.state_path = state_path
        self.location = location
        self.default_condition = validate_condition(default_condition)
        self.default_temperature_c = validate_temperature(default_temperature_c)

    def current(self, city: str | None = None) -> dict[str, Any]:
        with self._locked(exclusive=False):
            state = self._read_state()
        return self._record(state, city)

    def set_weather(
        self, condition: str, temperature_c: float | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        new_state = {
            "condition": validate_condition(condition),
            "temperature_c": validate_temperature(temperature_c),
            "updated_at": utc_now(),
        }
        with self._locked(exclusive=True):
            previous = self._read_state()
            self._write_state(new_state)
        return self._record(previous), self._record(new_state)

    def reset(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.set_weather(self.default_condition, self.default_temperature_c)

    def _record(self, state: dict[str, Any], city: str | None = None) -> dict[str, Any]:
        values = dict(SCENARIOS[state["condition"]])
        if state.get("temperature_c") is not None:
            values["temperature_c"] = state["temperature_c"]
        temperature = values["temperature_c"]
        today = datetime.now().date().isoformat()
        record = {
            "city": city or self.location.name,
            "latitude": self.location.latitude,
            "longitude": self.location.longitude,
            "time": state.get("updated_at") or utc_now(),
            **values,
            "dew_point_c": dew_point_c(temperature, values["relative_humidity_percent"]),
            "apparent_temperature_c": temperature,
            "wind_direction_degrees": 200,
            "sunrise": f"{today}T06:45",
            "sunset": f"{today}T18:30",
            "observed_at": utc_now(),
        }
        return normalize(record, source="weather-simulator", simulated=True)

    def _read_state(self) -> dict[str, Any]:
        default = {"condition": self.default_condition, "temperature_c": self.default_temperature_c}
        if not self.state_path.exists():
            return default
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            validate_condition(state["condition"])
            validate_temperature(state.get("temperature_c"))
        except (OSError, ValueError, KeyError, TypeError):
            return default
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp.{os.getpid()}")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    @contextmanager
    def _locked(self, exclusive: bool) -> Iterator[None]:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
