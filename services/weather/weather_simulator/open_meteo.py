"""Real weather backend using the Open-Meteo API (hosted, paid, or self-hosted)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .records import Location, normalize

CURRENT_VARIABLES = (
    "temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,"
    "precipitation,rain,snowfall,precipitation_probability,weather_code,"
    "cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,"
    "visibility,uv_index"
)

FetchJson = Callable[[str, float], dict[str, Any]]


class WeatherProviderError(RuntimeError):
    pass


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "weather-simulator/0.1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise WeatherProviderError(f"Open-Meteo returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise WeatherProviderError(f"Open-Meteo request failed: {error}") from error
    except json.JSONDecodeError as error:
        raise WeatherProviderError("Open-Meteo returned invalid JSON") from error


class OpenMeteoProvider:
    name = "open-meteo"

    def __init__(
        self,
        location: Location,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
        geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search",
        api_key: str | None = None,
        timeout: float = 10.0,
        fetch_json: FetchJson = _fetch_json,
    ) -> None:
        self.location = location
        self.base_url = base_url
        self.geocoding_url = geocoding_url
        self.api_key = api_key
        self.timeout = timeout
        self._fetch_json = fetch_json

    def current(self, city: str | None = None) -> dict[str, Any]:
        name, latitude, longitude = self._resolve(city)
        data = self._get(self.base_url, {
            "latitude": latitude,
            "longitude": longitude,
            "current": CURRENT_VARIABLES,
            "daily": "sunrise,sunset",
            "timezone": "auto",
            "forecast_days": 1,
        })
        try:
            current = data["current"]
            daily = data.get("daily", {})
            record = {
                "city": name,
                "latitude": latitude,
                "longitude": longitude,
                "time": current["time"],
                "temperature_c": current["temperature_2m"],
                "relative_humidity_percent": current.get("relative_humidity_2m"),
                "dew_point_c": current.get("dew_point_2m"),
                "weather_code": current["weather_code"],
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "wind_direction_degrees": current.get("wind_direction_10m"),
                "wind_gusts_kmh": current.get("wind_gusts_10m"),
                "precipitation_mm": current.get("precipitation"),
                "rain_mm": current.get("rain"),
                "snowfall_cm": current.get("snowfall"),
                "precipitation_probability_percent": current.get("precipitation_probability"),
                "pressure_hpa": current.get("pressure_msl"),
                "cloud_cover_percent": current.get("cloud_cover"),
                "uv_index": current.get("uv_index"),
                "apparent_temperature_c": current.get("apparent_temperature"),
                "visibility_m": current.get("visibility"),
                "sunrise": (daily.get("sunrise") or [None])[0],
                "sunset": (daily.get("sunset") or [None])[0],
            }
        except (KeyError, TypeError, IndexError) as error:
            raise WeatherProviderError(f"unexpected Open-Meteo response: missing {error}") from error
        return normalize(record, source="open-meteo", simulated=False)

    def _resolve(self, city: str | None) -> tuple[str, float, float]:
        if not city:
            if self.location.latitude is None or self.location.longitude is None:
                raise ValueError("city is required unless WEATHER_LATITUDE and WEATHER_LONGITUDE are set")
            return self.location.name, self.location.latitude, self.location.longitude
        if len(city) > 100:
            raise ValueError("city must be at most 100 characters")
        results = self._get(self.geocoding_url, {"name": city, "count": 1, "language": "en", "format": "json"})
        matches = results.get("results") or []
        if not matches:
            raise ValueError(f"no coordinates found for city: {city}")
        return city, float(matches[0]["latitude"]), float(matches[0]["longitude"])

    def _get(self, base_url: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.api_key:
            params = {**params, "apikey": self.api_key}
        return self._fetch_json(f"{base_url}?{urllib.parse.urlencode(params)}", self.timeout)
