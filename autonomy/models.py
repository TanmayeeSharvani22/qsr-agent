from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProposedAction:
    policy_id: str
    trigger_type: str
    summary: str
    evidence: dict[str, Any]
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class PolicyEvaluation:
    active: bool
    proposal: ProposedAction | None = None
    decision: dict[str, Any] | None = None