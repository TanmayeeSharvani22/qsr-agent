from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import urllib.parse
from dataclasses import replace
from pathlib import Path

from fastmcp import Client
from starlette.testclient import TestClient

from weather_simulator.config import Settings
from weather_simulator.events import WeatherEventPublisher
from weather_simulator.open_meteo import OpenMeteoProvider
from weather_simulator.records import Location
from weather_simulator.server import build_server, change_weather
from weather_simulator.simulator import SimulatedWeatherProvider

LOCATION = Location("Edge Retail Lab", 37.39, -121.96)


class RecordingPost:
    def __init__(self, status: int = 202) -> None:
        self.status = status
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str], timeout: float) -> int:
        self.calls.append((url, json.loads(body), headers))
        return self.status


class SimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.provider = SimulatedWeatherProvider(Path(self.directory.name) / "state.json", LOCATION)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_default_is_clear_and_dry(self) -> None:
        record = self.provider.current()
        self.assertEqual(record["condition"], "clear")
        self.assertFalse(record["is_raining"])
        self.assertTrue(record["simulated"])
        self.assertEqual(record["city"], "Edge Retail Lab")

    def test_rain_with_temperature_override_persists_across_instances(self) -> None:
        self.provider.set_weather("rain", 11.5)
        record = SimulatedWeatherProvider(self.provider.state_path, LOCATION).current()
        self.assertEqual(record["condition"], "rain")
        self.assertTrue(record["is_raining"])
        self.assertEqual(record["temperature_c"], 11.5)
        self.assertGreater(record["rain_mm"], 0)
        self.assertEqual(record["weather_description"], "Moderate rain")

    def test_record_matches_mcp_weather_server_fields(self) -> None:
        expected = {
            "city", "latitude", "longitude", "time", "temperature_c", "relative_humidity_percent",
            "dew_point_c", "weather_code", "weather_description", "wind_speed_kmh",
            "wind_direction_degrees", "wind_gusts_kmh", "precipitation_mm", "rain_mm", "snowfall_cm",
            "precipitation_probability_percent", "pressure_hpa", "cloud_cover_percent", "uv_index",
            "apparent_temperature_c", "visibility_m", "sunrise", "sunset",
        }
        self.assertLessEqual(expected, set(self.provider.current()))

    def test_invalid_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown condition"):
            self.provider.set_weather("hurricane")
        with self.assertRaisesRegex(ValueError, "between"):
            self.provider.set_weather("rain", 500)

    def test_corrupt_state_falls_back_to_default(self) -> None:
        self.provider.state_path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.provider.current()["condition"], "clear")


class PublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.provider = SimulatedWeatherProvider(Path(self.directory.name) / "state.json", LOCATION)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_rain_change_posts_qsr_weather_changed_envelope(self) -> None:
        post = RecordingPost()
        publisher = WeatherEventPublisher("http://qsr/autonomy/events", "qsr-001", "secret", post_json=post)
        result = change_weather(self.provider, publisher, "rain", 14)
        self.assertTrue(result["event"]["published"])
        _url, event, headers = post.calls[0]
        self.assertEqual(event["event_type"], "weather_changed")
        self.assertEqual(event["store_id"], "qsr-001")
        self.assertTrue(event["data"]["is_raining"])
        self.assertEqual(event["data"]["condition"], "rain")
        self.assertEqual(event["data"]["temperature_c"], 14)
        self.assertEqual(event["data"]["previous"]["condition"], "clear")
        self.assertEqual(headers["Authorization"], "Bearer secret")

    def test_insignificant_change_is_not_published(self) -> None:
        post = RecordingPost()
        publisher = WeatherEventPublisher("http://qsr/autonomy/events", "qsr-001", post_json=post)
        self.provider.set_weather("clear", 20.0)
        result = change_weather(self.provider, publisher, "clear", 20.4)
        self.assertFalse(result["event"]["published"])
        self.assertEqual(post.calls, [])

    def test_client_error_is_not_retried(self) -> None:
        post = RecordingPost(status=400)
        publisher = WeatherEventPublisher("http://qsr/autonomy/events", "qsr-001", post_json=post)
        result = change_weather(self.provider, publisher, "rain")
        self.assertFalse(result["event"]["published"])
        self.assertEqual(len(post.calls), 1)

    def test_without_webhook_only_state_changes(self) -> None:
        result = change_weather(self.provider, WeatherEventPublisher(None, "qsr-001"), "storm")
        self.assertFalse(result["event"]["published"])
        self.assertEqual(self.provider.current()["condition"], "storm")


class OpenMeteoTests(unittest.TestCase):
    def test_current_weather_maps_open_meteo_response(self) -> None:
        requested: list[dict[str, list[str]]] = []

        def fetch(url: str, timeout: float) -> dict:
            requested.append(urllib.parse.parse_qs(urllib.parse.urlparse(url).query))
            return {
                "current": {
                    "time": "2026-10-05T12:00", "temperature_2m": 12.3, "relative_humidity_2m": 91,
                    "dew_point_2m": 10.9, "apparent_temperature": 10.1, "precipitation": 2.1,
                    "rain": 2.1, "snowfall": 0.0, "precipitation_probability": 80, "weather_code": 61,
                    "cloud_cover": 100, "pressure_msl": 1003.2, "wind_speed_10m": 14.0,
                    "wind_direction_10m": 210, "wind_gusts_10m": 30.0, "visibility": 7000, "uv_index": 0.4,
                },
                "daily": {"sunrise": ["2026-10-05T07:05"], "sunset": ["2026-10-05T18:40"]},
            }

        provider = OpenMeteoProvider(LOCATION, api_key="paid-key", fetch_json=fetch)
        record = provider.current()
        self.assertEqual(record["condition"], "rain")
        self.assertTrue(record["is_raining"])
        self.assertEqual(record["temperature_c"], 12.3)
        self.assertFalse(record["simulated"])
        self.assertEqual(record["source"], "open-meteo")
        self.assertEqual(requested[0]["latitude"], ["37.39"])
        self.assertEqual(requested[0]["apikey"], ["paid-key"])

    def test_city_lookup_uses_geocoding(self) -> None:
        def fetch(url: str, timeout: float) -> dict:
            if "geocoding" in url:
                return {"results": [{"latitude": 51.5, "longitude": -0.12}]}
            return {"current": {"time": "t", "temperature_2m": 9.0, "weather_code": 0}}

        record = OpenMeteoProvider(Location("unused"), fetch_json=fetch).current("London")
        self.assertEqual((record["city"], record["latitude"]), ("London", 51.5))
        self.assertEqual(record["condition"], "clear")

    def test_missing_location_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "city is required"):
            OpenMeteoProvider(Location("Store")).current()


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.settings = Settings(
            location=LOCATION, state_path=Path(self.directory.name) / "state.json"
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _app(self, **overrides):
        settings = replace(self.settings, **overrides)
        return build_server(settings, settings.build_provider(), WeatherEventPublisher(None, "qsr-001"))

    def _tool_names(self, app) -> set[str]:
        async def names() -> set[str]:
            async with Client(app) as client:
                return {tool.name for tool in await client.list_tools()}

        return asyncio.run(names())

    def _call(self, app, name: str, arguments: dict):
        async def call():
            async with Client(app) as client:
                return await client.call_tool(name, arguments, raise_on_error=False)

        return asyncio.run(call())

    def test_read_tools_are_compatible_and_control_tools_hidden_by_default(self) -> None:
        self.assertEqual(self._tool_names(self._app()), {"get_current_weather", "get_weather_details"})

    def test_control_tools_can_be_enabled_for_simulator(self) -> None:
        names = self._tool_names(self._app(expose_control_tools=True))
        self.assertIn("set_simulated_weather", names)
        self.assertIn("reset_simulated_weather", names)

    def test_control_tools_never_exposed_for_real_weather(self) -> None:
        names = self._tool_names(self._app(backend="open-meteo", expose_control_tools=True))
        self.assertNotIn("set_simulated_weather", names)

    def test_weather_details_returns_structured_content(self) -> None:
        result = self._call(self._app(), "get_weather_details", {})
        self.assertEqual(result.structured_content["condition"], "clear")

    def test_invalid_control_input_is_a_tool_error(self) -> None:
        result = self._call(
            self._app(expose_control_tools=True),
            "set_simulated_weather",
            {"condition": "rain", "temperature_c": 500},
        )
        self.assertTrue(result.is_error)
        self.assertIn("between", result.content[0].text)

    def test_http_control_requires_token_when_configured(self) -> None:
        app = self._app(control_token="demo-token").http_app()
        with TestClient(app) as client:
            denied = client.post("/simulator/weather", json={"condition": "rain"})
            self.assertEqual(denied.status_code, 403)
            accepted = client.post(
                "/simulator/weather",
                json={"condition": "rain", "temperature_c": 13},
                headers={"Authorization": "Bearer demo-token"},
            )
            self.assertEqual(accepted.status_code, 200)
            self.assertTrue(accepted.json()["current"]["is_raining"])
            rejected = client.post(
                "/simulator/weather",
                json={"condition": "rain", "extra": 1},
                headers={"Authorization": "Bearer demo-token"},
            )
            self.assertEqual(rejected.status_code, 400)


if __name__ == "__main__":
    unittest.main()
