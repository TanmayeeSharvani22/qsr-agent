"""Command line: serve the MCP server, or control and inspect simulated weather."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import Any

from .config import Settings
from .events import WeatherEventPublisher
from .open_meteo import WeatherProviderError
from .server import build_server, change_weather
from .simulator import CONDITIONS, SimulatedWeatherProvider

logger = logging.getLogger("weather-simulator")

MIN_WATCH_INTERVAL_SECONDS = 60


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def _simulator(settings: Settings) -> SimulatedWeatherProvider:
    provider = settings.build_provider()
    if not isinstance(provider, SimulatedWeatherProvider):
        raise SystemExit("weather control commands require WEATHER_BACKEND=simulator")
    return provider


def _serve(settings: Settings, args: argparse.Namespace) -> None:
    app = build_server(settings, settings.build_provider(), settings.build_publisher())
    if args.transport == "stdio":
        app.run("stdio", show_banner=False)
        return
    transport = "http" if args.transport == "streamable-http" else args.transport
    app.run(transport, show_banner=False, host=args.host, port=args.port)


def _watch(settings: Settings, publisher: WeatherEventPublisher, interval: float, once: bool) -> None:
    """Poll the backend and publish significant changes; used with real weather."""
    provider = settings.build_provider()
    previous = None
    while True:
        try:
            current = provider.current()
        except (WeatherProviderError, ValueError) as error:
            logger.warning("weather poll failed: %s", error)
        else:
            if previous is not None:
                result = publisher.publish(previous, current)
                if result["published"] or result.get("event_id"):
                    logger.info("weather event: %s", json.dumps(result))
            previous = current
        if once:
            return
        time.sleep(interval)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="weather-simulator", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the MCP server (default: stdio)")
    serve.add_argument("--transport", choices=("stdio", "http", "streamable-http", "sse"), default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)

    set_cmd = sub.add_parser("set", help="set simulated weather and publish weather_changed")
    set_cmd.add_argument("condition", choices=CONDITIONS)
    set_cmd.add_argument("--temperature", type=float, dest="temperature_c")
    set_cmd.add_argument("--no-event", action="store_true", help="change state without publishing")

    reset = sub.add_parser("reset", help="restore the default simulated weather")
    reset.add_argument("--no-event", action="store_true")

    sub.add_parser("show", help="print the current weather record")

    watch = sub.add_parser("watch", help="poll the backend and publish weather_changed on change")
    watch.add_argument("--interval", type=float, default=600.0, help="seconds between polls")
    watch.add_argument("--once", action="store_true", help="poll once (baseline only)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    settings = Settings.from_env()

    try:
        if args.command in (None, "serve"):
            if args.command is None:
                args = serve.parse_args([])
            _serve(settings, args)
        elif args.command == "set":
            _print(change_weather(
                _simulator(settings), settings.build_publisher(),
                args.condition, args.temperature_c, publish_event=not args.no_event,
            ))
        elif args.command == "reset":
            _print(change_weather(
                _simulator(settings), settings.build_publisher(), None, publish_event=not args.no_event,
            ))
        elif args.command == "show":
            _print(settings.build_provider().current())
        elif args.command == "watch":
            if args.interval < MIN_WATCH_INTERVAL_SECONDS:
                raise ValueError(f"--interval must be at least {MIN_WATCH_INTERVAL_SECONDS} seconds")
            _watch(settings, settings.build_publisher(), args.interval, args.once)
    except (ValueError, WeatherProviderError) as error:
        raise SystemExit(f"error: {error}") from error


if __name__ == "__main__":
    main()
