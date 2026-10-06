"""Environment-driven configuration; selecting the backend is a deployment choice."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .events import WeatherEventPublisher
from .open_meteo import OpenMeteoProvider
from .records import Location
from .simulator import SimulatedWeatherProvider

BACKENDS = ("simulator", "open-meteo")


def _float(name: str) -> float | None:
    value = os.environ.get(name, "").strip()
    return float(value) if value else None


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    backend: str = "simulator"
    store_id: str = "qsr-001"
    location: Location = field(default_factory=lambda: Location("Demo Store"))
    state_path: Path = Path.home() / ".local/state/weather-simulator/state.json"
    default_condition: str = "clear"
    default_temperature_c: float | None = None
    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    open_meteo_api_key: str | None = None
    webhook_url: str | None = None
    webhook_token: str | None = None
    temperature_delta_c: float = 1.0
    control_token: str | None = None
    expose_control_tools: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        backend = os.environ.get("WEATHER_BACKEND", "simulator").strip().lower()
        if backend not in BACKENDS:
            raise ValueError(f"WEATHER_BACKEND must be one of: {', '.join(BACKENDS)}")
        delta = _float("WEATHER_EVENT_TEMPERATURE_DELTA_C")
        return cls(
            backend=backend,
            store_id=os.environ.get("WEATHER_STORE_ID", "qsr-001"),
            location=Location(
                os.environ.get("WEATHER_LOCATION_NAME", "Demo Store"),
                _float("WEATHER_LATITUDE"),
                _float("WEATHER_LONGITUDE"),
            ),
            state_path=Path(os.environ.get("WEATHER_SIM_STATE", str(cls.state_path))).expanduser(),
            default_condition=os.environ.get("WEATHER_SIM_DEFAULT_CONDITION", "clear"),
            default_temperature_c=_float("WEATHER_SIM_DEFAULT_TEMPERATURE_C"),
            open_meteo_base_url=os.environ.get("OPEN_METEO_BASE_URL", cls.open_meteo_base_url),
            open_meteo_geocoding_url=os.environ.get("OPEN_METEO_GEOCODING_URL", cls.open_meteo_geocoding_url),
            open_meteo_api_key=os.environ.get("OPEN_METEO_API_KEY") or None,
            webhook_url=os.environ.get("WEATHER_EVENT_WEBHOOK_URL") or None,
            webhook_token=os.environ.get("WEATHER_EVENT_WEBHOOK_TOKEN") or None,
            temperature_delta_c=1.0 if delta is None else delta,
            control_token=os.environ.get("WEATHER_SIM_CONTROL_TOKEN") or None,
            expose_control_tools=_flag("WEATHER_SIM_EXPOSE_CONTROL_TOOLS"),
        )

    def build_provider(self) -> SimulatedWeatherProvider | OpenMeteoProvider:
        if self.backend == "open-meteo":
            return OpenMeteoProvider(
                self.location,
                base_url=self.open_meteo_base_url,
                geocoding_url=self.open_meteo_geocoding_url,
                api_key=self.open_meteo_api_key,
            )
        return SimulatedWeatherProvider(
            self.state_path, self.location, self.default_condition, self.default_temperature_c
        )

    def build_publisher(self) -> WeatherEventPublisher:
        return WeatherEventPublisher(
            self.webhook_url, self.store_id, self.webhook_token, self.temperature_delta_c
        )
