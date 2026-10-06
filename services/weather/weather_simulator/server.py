"""MCP server exposing weather tools compatible with `mcp_weather_server`."""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from typing import Any, TypeVar

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import Settings
from .events import WeatherEventPublisher
from .open_meteo import OpenMeteoProvider, WeatherProviderError
from .records import format_summary
from .simulator import CONDITIONS, Condition, SimulatedWeatherProvider

Provider = SimulatedWeatherProvider | OpenMeteoProvider

LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1", "localhost"})
MAX_CONTROL_BODY_BYTES = 4096

T = TypeVar("T")


def _tool_errors(call: Callable[[], T]) -> T:
    # Expected input/provider failures become clean MCP errors instead of tracebacks.
    try:
        return call()
    except (ValueError, WeatherProviderError) as error:
        raise ToolError(str(error)) from error


def change_weather(
    provider: SimulatedWeatherProvider,
    publisher: WeatherEventPublisher,
    condition: str | None,
    temperature_c: float | None = None,
    publish_event: bool = True,
) -> dict[str, Any]:
    """Apply an operator weather change and optionally emit `weather_changed`."""
    if condition is None:
        previous, current = provider.reset()
    else:
        previous, current = provider.set_weather(condition, temperature_c)
    event = (
        publisher.publish(previous, current)
        if publish_event
        else {"published": False, "reason": "event publishing disabled for this change"}
    )
    return {"previous": previous, "current": current, "event": event}


def build_server(settings: Settings, provider: Provider, publisher: WeatherEventPublisher) -> FastMCP:
    app = FastMCP("weather")
    simulated = isinstance(provider, SimulatedWeatherProvider)

    @app.tool(
        name="get_current_weather",
        description=(
            "Get a human-readable summary of current weather for a city. "
            "Omit city to use the configured store location."
        ),
    )
    def get_current_weather(city: str | None = None) -> str:
        return _tool_errors(lambda: format_summary(provider.current(city)))

    @app.tool(
        name="get_weather_details",
        description=(
            "Get current weather as structured JSON: temperature_c, condition "
            "(clear, cloudy, fog, drizzle, rain, storm, snow), is_raining, "
            "precipitation, wind, humidity, source, simulated, and observed_at. "
            "Omit city to use the configured store location."
        ),
    )
    def get_weather_details(city: str | None = None) -> dict[str, Any]:
        return _tool_errors(lambda: provider.current(city))

    if simulated and settings.expose_control_tools:

        @app.tool(
            name="set_simulated_weather",
            description=(
                "DEMO ONLY: set simulated weather. Publishes a weather_changed event "
                "when a webhook is configured."
            ),
        )
        def set_simulated_weather(condition: Condition, temperature_c: float | None = None) -> dict[str, Any]:
            return _tool_errors(lambda: change_weather(provider, publisher, condition, temperature_c))

        @app.tool(
            name="reset_simulated_weather",
            description="DEMO ONLY: restore the default simulated weather.",
        )
        def reset_simulated_weather() -> dict[str, Any]:
            return change_weather(provider, publisher, None)

    _register_http_routes(app, settings, provider, publisher)
    return app


def _register_http_routes(
    app: FastMCP, settings: Settings, provider: Provider, publisher: WeatherEventPublisher
) -> None:
    """Health and demo-control endpoints, served only by HTTP transports."""

    @app.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "backend": settings.backend})

    if not isinstance(provider, SimulatedWeatherProvider):
        return

    def authorized(request: Request) -> bool:
        if settings.control_token:
            supplied = request.headers.get("authorization", "")
            return hmac.compare_digest(supplied.encode(), f"Bearer {settings.control_token}".encode())
        return request.client is not None and request.client.host in LOOPBACK_CLIENTS

    def denied() -> JSONResponse:
        return JSONResponse(
            {"ok": False, "error": "control requires a loopback client or WEATHER_SIM_CONTROL_TOKEN"},
            status_code=403,
        )

    async def read_body(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if len(raw) > MAX_CONTROL_BODY_BYTES:
            raise ValueError("request body too large")
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    @app.custom_route("/simulator/weather", methods=["GET", "POST"])
    async def simulator_weather(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        if request.method == "GET":
            return JSONResponse({"ok": True, "weather": provider.current(), "conditions": list(CONDITIONS)})
        try:
            payload = await read_body(request)
            unknown = set(payload) - {"condition", "temperature_c", "publish_event"}
            if unknown:
                raise ValueError(f"unsupported fields: {', '.join(sorted(unknown))}")
            condition = payload.get("condition")
            if not isinstance(condition, str):
                raise ValueError("condition is required")
            publish_event = payload.get("publish_event", True)
            if not isinstance(publish_event, bool):
                raise ValueError("publish_event must be a boolean")
            result = change_weather(
                provider, publisher, condition, payload.get("temperature_c"), publish_event
            )
        except (ValueError, json.JSONDecodeError) as error:
            return JSONResponse({"ok": False, "error": str(error)}, status_code=400)
        return JSONResponse({"ok": True, **result})

    @app.custom_route("/simulator/weather/reset", methods=["POST"])
    async def simulator_reset(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        return JSONResponse({"ok": True, **change_weather(provider, publisher, None)})
