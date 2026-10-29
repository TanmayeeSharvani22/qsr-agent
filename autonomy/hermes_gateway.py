"""Client and supervisor for the always-running Hermes gateway (API server).

Operator chat and event decisions both reach one long-lived `hermes gateway run`
process, so Hermes's built-in memory review completes after chat turns. `hermes -z`
is not used: it hands turns to an auto-started gateway that ignores its toolset limits.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

API_PORT = int(os.environ.get("QSR_HERMES_API_PORT", "8642"))
API_URL = f"http://127.0.0.1:{API_PORT}"
EVENTS_PROFILE = os.environ.get("QSR_HERMES_EVENTS_PROFILE", "qsr-events")
# Loopback only: never route the gateway call through a corporate proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def events_profile_key() -> str:
    """The events profile authenticates with its own key, kept in that profile's .env."""
    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    try:
        lines = (home / "profiles" / EVENTS_PROFILE / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        if line.startswith("API_SERVER_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


class GatewayError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class HermesGateway:
    """One profile on the shared gateway; the default profile serves operator chat."""

    def __init__(self, key: str, base_url: str = API_URL, timeout: float = 300.0) -> None:
        self.key = key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def operator(cls, timeout: float = 300.0) -> HermesGateway:
        return cls(os.environ.get("QSR_HERMES_API_KEY", ""), API_URL, timeout)

    @classmethod
    def events(cls, timeout: float = 300.0) -> HermesGateway:
        return cls(events_profile_key(), f"{API_URL}/p/{EVENTS_PROFILE}", timeout)

    def _open(self, method: str, path: str, body: dict[str, Any] | None, timeout: float | None):
        if not self.key:
            raise GatewayError("Hermes gateway API key is not configured")
        request = urllib.request.Request(
            self.base_url + path, method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
        )
        try:
            return _OPENER.open(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read() or b"{}").get("error", {})
                message = detail.get("message") if isinstance(detail, dict) else str(detail)
            except (ValueError, AttributeError):
                message = None
            raise GatewayError(message or f"Hermes gateway returned HTTP {error.code}", error.code) from error
        except (urllib.error.URLError, OSError) as error:
            raise GatewayError(f"Hermes gateway unreachable: {error}") from error

    def _json(self, method: str, path: str, body: dict[str, Any] | None = None,
              timeout: float | None = None) -> dict[str, Any]:
        with self._open(method, path, body, timeout) as response:
            return json.loads(response.read() or b"{}")

    def healthy(self) -> bool:
        try:
            with _OPENER.open(f"{API_URL}/health", timeout=3) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def create_session(self, title: str) -> str:
        return self._json("POST", "/api/sessions", {"title": title}, timeout=30)["session"]["id"]

    def session_exists(self, session_id: str) -> bool:
        try:
            self._json("GET", f"/api/sessions/{session_id}", timeout=30)
            return True
        except GatewayError as error:
            if error.status == 404:
                return False
            raise

    def stream_chat(self, session_id: str, text: str, instructions: str | None = None) -> Iterator[dict[str, Any]]:
        """Run one turn in a persistent session; yields delta/tool/completed events."""
        body: dict[str, Any] = {"input": text}
        if instructions:
            body["instructions"] = instructions
        with self._open("POST", f"/api/sessions/{session_id}/chat/stream", body, None) as response:
            name = ""
            for raw in response:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        data = json.loads(line[5:])
                    except ValueError:
                        continue
                    if name == "error":
                        raise GatewayError(str(data.get("message") or "Hermes turn failed"))
                    yield {"event": name, **data}
                    if name == "done":
                        return

    def complete(self, prompt: str) -> str:
        """Stateless turn: fresh session with this profile's memory, no history."""
        result = self._json("POST", "/v1/chat/completions", {
            "model": "hermes-agent", "messages": [{"role": "user", "content": prompt}]})
        try:
            return result["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as error:
            raise GatewayError("Hermes gateway returned no completion") from error


def wait_until_healthy(gateway: HermesGateway, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if gateway.healthy():
            return True
        time.sleep(2)
    return False


class HermesSessions:
    """Named always-on Hermes sessions, persisted so they survive UI restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        sessions = {}
        for name, entry in data.items():
            if isinstance(entry, str):
                entry = {"id": entry, "used_at": time.time()}
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                sessions[name] = entry
        return sessions

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(self.path)

    def get(self, name: str, gateway: HermesGateway, title: str, max_idle_seconds: float = 0) -> str:
        """The named session, or a new one when it is missing or idle longer than max_idle_seconds."""
        with self._lock:
            data = self._load()
            entry = data.get(name)
            idle = time.time() - float(entry.get("used_at", 0)) if entry else 0.0
            if entry and not (max_idle_seconds and idle > max_idle_seconds) and gateway.session_exists(entry["id"]):
                session_id = entry["id"]
            else:
                # Hermes requires unique titles; "New chat" can be pressed several times a minute.
                session_id = gateway.create_session(f"{title} {datetime.now(UTC):%Y-%m-%d %H:%M} {secrets.token_hex(3)}")
            data[name] = {"id": session_id, "used_at": time.time()}
            self._save(data)
            return session_id

    def set(self, name: str, session_id: str) -> None:
        with self._lock:
            data = self._load()
            data[name] = {"id": session_id, "used_at": time.time()}
            self._save(data)

    def forget(self, name: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(name, None) is not None:
                self._save(data)


class GatewaySupervisor:
    """Keeps `hermes gateway run` alive for the lifetime of the operator UI."""

    def __init__(self, hermes: str | None = None) -> None:
        self.hermes = hermes or os.environ.get("HERMES_BIN") or shutil.which("hermes") or "hermes"
        self._stop = threading.Event()
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["API_SERVER_KEY"] = environment.get("QSR_HERMES_API_KEY", "")
        environment["API_SERVER_HOST"] = "127.0.0.1"
        environment["API_SERVER_PORT"] = str(API_PORT)
        # Same as the previous per-question Hermes runs: no corporate proxy, loopback direct.
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            environment.pop(name, None)
        environment["NO_PROXY"] = environment["no_proxy"] = "localhost,127.0.0.1,::1"
        return environment

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="hermes-gateway", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._process = subprocess.Popen(
                    [self.hermes, "gateway", "run", "--replace", "--external-supervisor"],
                    # Neutral cwd: the repo's AGENTS.md is developer guidance, not agent context.
                    env=self._environment(), cwd=Path.home(), stdin=subprocess.DEVNULL, start_new_session=True,
                )
                code = self._process.wait()
            except OSError as error:
                code = f"could not start ({error})"
            if self._stop.is_set():
                return
            backoff = 2.0 if time.monotonic() - started > 60 else min(backoff * 2, 60.0)
            print(f"[QSR UI] Hermes gateway exited ({code}); restarting in {backoff:.0f}s", flush=True)
            self._stop.wait(backoff)

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
