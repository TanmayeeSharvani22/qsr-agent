"""Learner runs shared by the CLI (scripts/learn.py) and the operator UI.

The model proposes rules, the records verify them, and the skill write is staged in the
learner profile's Hermes pending store; Hermes's own /skills approve handler applies it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from .learning import (
    Journal, coverage_gaps, induce_missing_rules, learner_prompt, parse_rules, parse_skill_meta,
    read_skill_meta, render_skill, skill_sha, validate_learned_skill, verify_rules,
)

PROFILE = os.environ.get("QSR_LEARNER_PROFILE", "qsr-learner")
LEARNER_HOME = Path(os.environ.get("QSR_LEARNER_HERMES_HOME", Path.home() / f".hermes/profiles/{PROFILE}"))
HERMES_BIN = os.environ.get("HERMES_BIN", os.path.expanduser("~/.local/bin/hermes"))
TIMEOUT = float(os.environ.get("QSR_LEARNER_TIMEOUT", "600"))

Progress = Callable[[str], None]


class LearnerError(RuntimeError):
    pass


def hermes_bin() -> str:
    hermes = HERMES_BIN if os.path.isfile(HERMES_BIN) else shutil.which("hermes")
    if not hermes:
        raise LearnerError(f"hermes not found at {HERMES_BIN} or on PATH")
    return hermes


def hermes_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HERMES_CHECK_FOR_UPDATES"] = "false"
    env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(name, None)
    return env


def pending_dir() -> Path:
    return LEARNER_HOME / "pending" / "skills"


def setup_profile(journal: Journal) -> str:
    """Create/refresh the learner profile: operator model settings, learned-skills dir, write approval on."""
    if not LEARNER_HOME.is_dir():
        # Hermes resolves its runtime from the profile root, so the home must be a real profile.
        subprocess.run([hermes_bin(), "profile", "create", PROFILE, "--no-skills", "--no-alias"],
                       check=True, env=hermes_env())
        if not LEARNER_HOME.is_dir():
            raise LearnerError(f"Hermes created profile '{PROFILE}' outside {LEARNER_HOME}; "
                               "set QSR_LEARNER_HERMES_HOME to that profile directory")
    config_path = LEARNER_HOME / "config.yaml"
    config = (yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}) or {}
    source_path = Path(os.environ.get("HERMES_CONFIG", Path.home() / ".hermes/config.yaml"))
    source = (yaml.safe_load(source_path.read_text(encoding="utf-8")) if source_path.exists() else {}) or {}
    # Reuse the working model/provider settings; nothing else from the operator profile.
    for key in ("model", "providers"):
        if source.get(key):
            config[key] = source[key]
    model = config.setdefault("model", {})
    model["max_tokens"] = max(int(model.get("max_tokens") or 0), 4096)
    skills_dir = str(journal.skills_dir.resolve())
    journal.skills_dir.mkdir(parents=True, exist_ok=True)
    config["skills"] = {
        **(config.get("skills") or {}),
        "external_dirs": [skills_dir], "create_dir": skills_dir,
        "write_approval": True, "guard_agent_created": True, "project_discovery": False,
    }
    # The learner only writes learned skills: no MCP services, no memory.
    config["mcp_servers"] = {}
    config["memory"] = {**(config.get("memory") or {}), "memory_enabled": False, "user_profile_enabled": False}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return f"Learner profile '{PROFILE}' at {LEARNER_HOME}: skills -> {skills_dir}, write_approval on"


def counts_by_service(records: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    """Unlearnt operator responses per service and event type (silent events excluded)."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        if record["operator"]["kind"] != "none":
            counts[record["event"]["service"]][record["event"]["type"]] += 1
    return counts


def catalog_tools(catalog: Any) -> list[dict[str, Any]]:
    tools = []
    for name, tool in catalog.tools.items():
        entry = {"name": name, "description": tool.description, "read_only": tool.read_only,
                 "required_reads": list(tool.required_reads)}
        if not tool.read_only:
            try:
                entry["inputSchema"] = catalog.schema(name)
            except Exception as error:  # noqa: BLE001 - schema is optional context for the learner
                print(f"warning: no schema for {name}: {error}", file=sys.stderr)
        tools.append(entry)
    return tools


def complete(prompt: str) -> str:
    """One completion from the learner profile's model endpoint.

    `hermes -z` is not used: one-shot Hermes hides skill_manage and stalled on this prompt, so the
    learner returns rules and Hermes's own pending store handles review and approval.
    """
    config = yaml.safe_load((LEARNER_HOME / "config.yaml").read_text(encoding="utf-8")) or {}
    model = config.get("model") or {}
    base_url, name = model.get("base_url"), model.get("default")
    if not base_url or not name:
        raise LearnerError("learner profile has no model.base_url/model.default; run: learn.py setup")
    provider = model.get("provider") or "custom"
    extra = ((config.get("providers") or {}).get(provider) or {}).get("extra_body") or {}
    body = {"model": name, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(os.environ.get("QSR_LEARNER_MAX_TOKENS", "2048")), "temperature": 0.2, **extra}
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {model.get('api_key') or 'none'}"},
    )
    host = urllib.parse.urlparse(base_url).hostname or ""
    handlers = [urllib.request.ProxyHandler({})] if host in {"localhost", "127.0.0.1", "::1"} else []
    try:
        with urllib.request.build_opener(*handlers).open(request, timeout=TIMEOUT) as response:
            payload = json.load(response)
    except (OSError, ValueError) as error:
        raise LearnerError(f"learner model call failed: {error}") from error
    return (payload["choices"][0]["message"].get("content") or "").strip()


def _plain(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: rule[key] for key in ("event", "when", "when_any", "propose", "intent") if key in rule}
            for rule in rules]


def _refine(prompt: str, accepted: list[dict[str, Any]], records: list[dict[str, Any]],
            tools: list[dict[str, Any]], min_support: int, progress: Progress) -> list[dict[str, Any]]:
    """One round asking only for rules that cover operator changes the verified rules miss."""
    gaps = coverage_gaps(accepted, records, min_support)
    if not gaps:
        return accepted
    for gap in gaps:
        progress(f"  gap: {gap}")
    reply = complete(
        prompt + "\n\nVerified rules so far (JSON):\n" + json.dumps(_plain(accepted))
        + "\n\nCoverage gaps (operators made these changes in records no rule matches):\n- "
        + "\n- ".join(gaps)
        + "\nOther fields (for example event.estimated_wait_minutes or a current context setting) may explain "
        'them. Return ONLY {"rules": [...]} with additional rules for these gaps.'
    )
    try:
        refined, dropped = verify_rules(_plain(accepted) + parse_rules(reply), records, tools, min_support)
    except ValueError as error:
        progress(f"  refinement ignored: {error}")
        return accepted
    for reason in dropped:
        progress(f"  dropped {reason}")
    progress(f"  refinement: {len(accepted)} -> {len(refined)} rules; "
             f"{len(coverage_gaps(refined, records, min_support))} gaps left")
    return refined if len(refined) >= len(accepted) else accepted


def learn_skill(prompt: str, service: str, records: list[dict[str, Any]], tools: list[dict[str, Any]],
                existing: str | None, min_support: int, progress: Progress = print) -> str:
    """Model proposes rules; only rules the records support are rendered. One repair round."""
    reply = complete(prompt)
    for attempt in range(2):
        try:
            accepted, dropped = verify_rules(parse_rules(reply), records, tools, min_support)
            for reason in dropped:
                progress(f"  dropped {reason}")
            if not accepted:
                raise ValueError("no proposed rule is supported by the records")
            accepted = _refine(prompt, accepted, records, tools, min_support, progress)
            induced = induce_missing_rules(accepted, records, min_support)
            if induced:
                accepted, _dropped = verify_rules(_plain(accepted) + induced, records, tools, min_support)
                progress(f"  induced {len(induced)} rules from records for remaining gaps; "
                         f"{len(coverage_gaps(accepted, records, min_support))} gaps left")
            text = render_skill(service, accepted, tools, existing)
            validate_learned_skill(text, service, tools)
            progress(f"  kept {len(accepted)} verified rules")
            return text
        except (ValueError, yaml.YAMLError) as error:
            if attempt:
                raise LearnerError(f"learner output rejected: {error}") from error
            progress(f"learner output rejected ({error}); asking for a correction...")
            reply = complete(
                prompt + "\n\nYour previous reply was rejected: " + str(error)
                + "\nPrevious reply (untrusted):\n" + reply[:6000]
                + '\nReturn the corrected JSON object {"rules": [...]} only.'
            )
    raise AssertionError("unreachable")


def stage(service: str, text: str, existing: bool) -> str:
    """Stage the write in the learner profile's Hermes pending store; /skills approve applies it."""
    pending_id = uuid.uuid4().hex[:8]
    action = "edit" if existing else "create"
    description = parse_skill_meta(text)["description"][:140]
    record = {
        "id": pending_id, "subsystem": "skills", "action": action,
        "summary": f"{'rewrite' if existing else 'create'} 'learned-{service}' - {description} ({len(text)} chars)",
        "origin": "foreground", "created_at": time.time(),
        "payload": {"action": action, "name": f"learned-{service}", "content": text},
    }
    pending_dir().mkdir(parents=True, exist_ok=True)
    (pending_dir() / f"{pending_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return pending_id


def run_service(journal: Journal, service: str, tools: list[dict[str, Any]], min_records: int = 5,
                min_support: int = 2, progress: Progress = print) -> dict[str, Any] | None:
    """Learn one service's event types that have at least ``min_records`` operator responses."""
    if any(run.get("status") == "staged" and run["service"] == service for run in journal.runs()):
        raise LearnerError(f"learned-{service} already has a staged change; approve or reject it first")
    records = journal.records()
    ready = {event for event, count in counts_by_service(records).get(service, {}).items() if count >= min_records}
    if service == "unknown" or not ready:
        return None
    batch = [record for record in records if record["event"]["service"] == service and record["event"]["type"] in ready]
    path = journal.skill_path(service)
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    prompt = learner_prompt(service, batch, existing, tools, min_support=min_support)
    progress(f"learned-{service}: asking learner with {len(batch)} records ({', '.join(sorted(ready))})...")
    text = learn_skill(prompt, service, batch, tools, existing, min_support, progress)
    pending_id = stage(service, text, path.is_file())
    run = {
        "run_id": f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{service}-{uuid.uuid4().hex[:6]}",
        "service": service, "events": sorted(ready), "status": "staged",
        "record_ids": [record["id"] for record in batch], "skill_sha_before": skill_sha(path),
        "pending_ids": [pending_id], "created_at": datetime.now(UTC).isoformat(),
    }
    journal.save_run(run)
    return {**run, "content": text}


def pending_writes() -> list[dict[str, Any]]:
    directory = pending_dir()
    records = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda record: record.get("created_at", 0))


def hermes_skills_command(*args: str) -> str:
    """Run Hermes's own `/skills ...` handler for the learner profile (no interactive session needed)."""
    runtime = json.loads(subprocess.run(
        [hermes_bin(), "--print-runtime-command"], capture_output=True, text=True, check=True, env=hermes_env(),
    ).stdout)
    match = re.search(r"sys\.path\.insert\(0, '([^']+)'\)", runtime[3])
    if not match:
        raise LearnerError("cannot locate the Hermes install from its runtime command")
    code = (f"import sys; sys.path.insert(0, {match.group(1)!r}); import hermes_bootstrap; "
            "from hermes_cli.write_approval_commands import handle_pending_subcommand; "
            f"print(handle_pending_subcommand('skills', {list(args)!r}))")
    result = subprocess.run([runtime[0], "-I", "-c", code], capture_output=True, text=True, timeout=120,
                            env={**hermes_env(), "HERMES_HOME": str(LEARNER_HOME)}, cwd="/tmp")
    if result.returncode:
        raise LearnerError(f"Hermes /skills {' '.join(args)} failed: {result.stderr.strip()[-500:]}")
    return result.stdout.strip()


def finalize(journal: Journal, progress: Progress = print) -> list[dict[str, Any]]:
    """Archive records of staged runs whose skill change was approved; dismiss rejected runs."""
    changed = []
    for run in journal.runs():
        if run.get("status") != "staged":
            continue
        path = journal.skill_path(run["service"])
        sha = skill_sha(path)
        waiting = [pid for pid in run.get("pending_ids", []) if (pending_dir() / f"{pid}.json").exists()]
        if sha and sha != run.get("skill_sha_before"):
            try:
                read_skill_meta(path)
            except (OSError, ValueError, yaml.YAMLError) as error:
                progress(f"{run['run_id']}: learned-{run['service']} changed but is invalid ({error}); fix it first")
                continue
            moved = journal.archive(set(run["record_ids"]), run["run_id"], sha)
            run.update(status="learnt", skill_sha=sha, finalized_at=datetime.now(UTC).isoformat())
            progress(f"{run['run_id']}: learned-{run['service']} updated ({sha}); archived {moved} records")
        elif waiting:
            progress(f"{run['run_id']}: awaiting approval of {', '.join(waiting)}")
            continue
        else:
            run.update(status="dismissed", finalized_at=datetime.now(UTC).isoformat())
            progress(f"{run['run_id']}: no approved change; records stay unlearnt")
        journal.save_run(run)
        changed.append(run)
    return changed


def decide(journal: Journal, pending_id: str, approve: bool) -> dict[str, Any]:
    """Approve or reject a staged skill write through Hermes, then finalize the run."""
    if not re.fullmatch(r"[0-9a-f]{8}", pending_id) or not (pending_dir() / f"{pending_id}.json").exists():
        raise LearnerError("unknown pending skill write")
    message = hermes_skills_command("approve" if approve else "reject", pending_id)
    if (pending_dir() / f"{pending_id}.json").exists():
        raise LearnerError(f"Hermes did not apply the decision: {message}")
    runs = finalize(journal, progress=lambda _line: None)
    return {"message": message, "runs": runs}
