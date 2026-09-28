from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class MenuChange:
    item_id: str
    available: bool
    reason: str


@dataclass(frozen=True)
class MenuDecision:
    summary: str
    confidence: float
    changes: tuple[MenuChange, ...]
    raw_response: str


class MenuAdvisor(Protocol):
    def decide(
        self,
        event_type: str,
        event_data: dict[str, Any],
        context: dict[str, Any],
    ) -> MenuDecision: ...


def parse_menu_decision(
    response: str, menu_item_ids: set[str]
) -> MenuDecision:
    text = response.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("Hermes advisor returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("Hermes advisor response must be a JSON object")

    summary = payload.get("summary")
    confidence = payload.get("confidence")
    raw_changes = payload.get("changes")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        raise ValueError("Hermes advisor summary must contain 1-500 characters")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("Hermes advisor confidence must be a number")
    if not 0 <= float(confidence) <= 1:
        raise ValueError("Hermes advisor confidence must be between 0 and 1")
    if not isinstance(raw_changes, list) or len(raw_changes) > 3:
        raise ValueError("Hermes advisor changes must be a list of at most 3 items")

    changes: list[MenuChange] = []
    seen: set[str] = set()
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            raise ValueError("each Hermes menu change must be an object")
        item_id = raw_change.get("item_id")
        available = raw_change.get("available")
        reason = raw_change.get("reason")
        if item_id not in menu_item_ids:
            raise ValueError(f"Hermes advisor returned unknown menu item: {item_id}")
        if item_id in seen:
            raise ValueError(f"Hermes advisor returned duplicate menu item: {item_id}")
        if not isinstance(available, bool):
            raise ValueError("Hermes advisor availability must be a boolean")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
            raise ValueError("Hermes menu-change reason must contain 1-300 characters")
        seen.add(item_id)
        changes.append(MenuChange(item_id, available, reason.strip()))
    return MenuDecision(
        summary.strip(), float(confidence), tuple(changes), response.strip()
    )


class HermesRunner:
    def __init__(self, skill_path: Path | None = None) -> None:
        self.hermes = os.environ.get(
            "HERMES_BIN", os.path.expanduser("~/.local/bin/hermes")
        )
        self.timeout = float(os.environ.get("QSR_ADVISOR_TIMEOUT", "90"))
        self.reasoning = os.environ.get("QSR_ADVISOR_REASONING", "none")
        self.model = os.environ.get(
            "QSR_ADVISOR_MODEL", "OpenVINO/Qwen3-8B-int4-ov"
        )
        self.base_url = os.environ.get(
            "QSR_ADVISOR_BASE_URL", "http://127.0.0.1:4444/v3"
        )
        self.api_key = os.environ.get(
            "QSR_ADVISOR_API_KEY", "local-ovms-no-auth"
        )
        self.skill_path = skill_path or (
            Path(__file__).resolve().parent.parent
            / "qsr-skills/event-menu-decisions/SKILL.md"
        )
        self._call_lock = threading.Lock()

    def complete(self, prompt: str) -> str:
        hermes = self.hermes if os.path.isfile(self.hermes) else shutil.which(self.hermes)
        if not hermes:
            raise RuntimeError(f"Hermes advisor binary not found: {self.hermes}")
        with self._call_lock, tempfile.TemporaryDirectory(
            prefix="qsr-hermes-advisor-"
        ) as temporary:
            environment = os.environ.copy()
            environment["HERMES_CHECK_FOR_UPDATES"] = "false"
            environment["HERMES_IGNORE_RULES"] = "1"
            environment["HERMES_MAX_ITERATIONS"] = "1"
            environment.pop("HERMES_KANBAN_TASK", None)
            environment["NO_PROXY"] = "localhost,127.0.0.1,::1"
            environment["no_proxy"] = "localhost,127.0.0.1,::1"
            for proxy_name in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                environment.pop(proxy_name, None)
            try:
                process = subprocess.Popen(
                    [
                        hermes,
                        "--reasoning",
                        self.reasoning,
                        "--toolsets",
                        "context_engine",
                        "-z",
                        prompt,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    stdin=subprocess.DEVNULL,
                    cwd=Path(temporary),
                    env=environment,
                    start_new_session=True,
                )
                try:
                    stdout, stderr = process.communicate(timeout=self.timeout)
                except subprocess.TimeoutExpired as error:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise RuntimeError(
                        f"Hermes advisor timed out after {self.timeout:.0f}s"
                    ) from error
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    f"Hermes advisor timed out after {self.timeout:.0f}s"
                ) from error
        if process.returncode != 0:
            message = (stderr or "Hermes advisor failed").strip()[:1000]
            raise RuntimeError(message)
        return stdout

    def _config(self) -> dict[str, Any]:
        return {
            "check_for_updates": False,
            "model": {
                "provider": "custom",
                "name": self.model,
                "default": self.model,
                "context_length": 64000,
                "max_tokens": 128,
                "streaming": False,
            },
            "custom_providers": [
                {
                    "name": "custom",
                    "base_url": self.base_url,
                    "api_key": self.api_key,
                    "model": self.model,
                    "models": [self.model],
                    "api_mode": "chat",
                    "context_length": 64000,
                    "request_timeout_seconds": self.timeout,
                    "stale_timeout_seconds": self.timeout,
                    "extra_body": {
                        "chat_template_kwargs": {"enable_thinking": False}
                    },
                }
            ],
            "agent": {
                "max_turns": 1,
                "run_budget_seconds": self.timeout,
                "reasoning_effort": self.reasoning,
            },
            "tools": {"tool_search": {"enabled": False}},
        }

class HermesMenuAdvisor(HermesRunner):
    def decide(
        self,
        event_type: str,
        event_data: dict[str, Any],
        context: dict[str, Any],
    ) -> MenuDecision:
        skill = self.skill_path.read_text(encoding="utf-8")
        menu_item_ids = {
            item.get("id") for item in context.get("menu", {}).get("items", [])
            if isinstance(item.get("id"), str)
        }
        if not menu_item_ids:
            raise ValueError("kiosk context contains no menu items")
        return parse_menu_decision(
            self.complete(self._prompt(skill, event_type, event_data, context)),
            menu_item_ids,
        )

    @staticmethod
    def _prompt(
        skill: str,
        event_type: str,
        event_data: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        operations = context.get("operations", {})
        weather = context.get("weather", {})
        activity = context.get("recent_activity", {})
        menu = context.get("menu", {})
        decision_context = {
            "event": {"type": event_type, "data": event_data},
            "state": {
                "queue": operations.get("queue_count"),
                "wait_min": operations.get("estimated_wait_minutes"),
                "staff": operations.get("staff_on_duty"),
                "orders_15m": activity.get("orders_last_15_minutes"),
                "abandoned": activity.get("abandoned_sessions"),
                "weather": {
                    "condition": weather.get("condition"),
                    "raining": weather.get("is_raining"),
                    "temp_c": weather.get("temperature_c"),
                },
                "menu": [
                    {"id": item.get("id"), "available": item.get("available")}
                    for item in menu.get("items", [])
                    if isinstance(item, dict)
                ],
                "observed_at": context.get("observed_at"),
            },
        }
        return (
            "Use this skill to decide a bounded menu recommendation. You have no tools; "
            "recommend only, never execute.\n"
            f"<skill>\n{skill}\n</skill>\n\n"
            f"<state>{json.dumps(decision_context, separators=(',', ':'))}</state>\n"
            "Return ONLY JSON with exactly: "
            '{"summary":"brief overall rationale","confidence":0.0,'
            '"changes":[{"item_id":"an exact live menu id",'
            '"available":true,"reason":"item-specific rationale"}]}. '
            "Use an empty changes list when no menu change is justified."
        )
