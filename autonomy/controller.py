from __future__ import annotations

import threading
import json
from typing import Any, Protocol

from .models import PolicyEvaluation
from .store import ProposalStore


class ToolClient(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]: ...


class EventPolicy(Protocol):
    policy_id: str
    event_type: str
    context_tool: str | None

    def evaluate_event(self, event: dict[str, Any], was_active: bool) -> PolicyEvaluation: ...


class AutonomyController:
    def __init__(
        self,
        client: ToolClient,
        store: ProposalStore,
        event_policies: list[EventPolicy] | None = None,
    ):
        self.client = client
        self.store = store
        self.event_policies = {
            policy.event_type: policy for policy in (event_policies or [])
        }
        self.policy_ids = {
            policy.policy_id for policy in self.event_policies.values()
        }
        self.store.supersede_unregistered(self.policy_ids)
        self.latest_events: dict[str, dict[str, Any]] = {}
        self._event_lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        with self._worker_lock:
            if self._worker and self._worker.is_alive():
                return
            self.store.recover_events()
            self._stop.clear()
            self._wake.set()
            self._worker = threading.Thread(target=self._work_events, name="qsr-event-worker", daemon=True)
            self._worker.start()

    def stop(self) -> None:
        with self._worker_lock:
            self._stop.set()
            self._wake.set()
            if self._worker:
                self._worker.join()

    def enqueue_event(self, event: dict[str, Any]) -> dict[str, Any]:
        self._validate_event(event)
        result = self.store.enqueue_event(event)
        self._wake.set()
        return result

    def _work_events(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            while not self._stop.is_set():
                event = self.store.claim_event()
                if event is None:
                    break
                try:
                    with self._event_lock:
                        self._receive_event(event, reserved=True)
                except Exception as error:
                    self.store.finish_event(event, str(error))
                else:
                    self.store.finish_event(event)

    def receive_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._event_lock:
            return self._receive_event(event)

    def _validate_event(self, event: dict[str, Any]) -> EventPolicy:
        event_id = event.get("event_id", "")
        if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 200:
            raise ValueError("event_id is required")
        event_type = event.get("event_type", "")
        if not isinstance(event_type, str) or not event_type.strip() or len(event_type) > 200:
            raise ValueError("event_type is required")
        if not isinstance(event.get("data"), dict):
            raise ValueError("data must be an object")
        if len(json.dumps(event, allow_nan=False)) > 32768:
            raise ValueError("event exceeds 32 KiB")
        policy = self.event_policies.get(event_type) or self.event_policies.get("*")
        if policy is None:
            supported = ", ".join(sorted(self.event_policies))
            raise ValueError(f"unsupported event_type; expected one of: {supported}")
        catalog = getattr(policy, "catalog", None)
        if catalog and event.get("store_id", catalog.restaurant_id) != catalog.restaurant_id:
            raise ValueError("event restaurant does not match this deployment")
        return policy

    def _receive_event(self, event: dict[str, Any], reserved: bool = False) -> dict[str, Any]:
        policy = self._validate_event(event)
        event_id, event_type = event["event_id"], event["event_type"]
        if not reserved and not self.store.record_event(event_id):
            return {"duplicate": True, "event_id": event_id, "proposal": None}
        self.store.save_decision(event_id, {"event": event, "status": "processing"})
        evaluation_event = dict(event)
        try:
            context_tool = getattr(policy, "context_tool", None)
            if context_tool:
                evaluation_event["context"] = self.client.call_tool(context_tool)
            was_active = self.store.is_policy_active(policy.policy_id)
            if hasattr(policy, "report_progress"):
                policy.report_progress = lambda progress: self.store.save_decision(
                    event_id, {"event": event, "status": "processing", "progress": progress}
                )
            try:
                evaluation = policy.evaluate_event(evaluation_event, was_active)
            finally:
                if hasattr(policy, "report_progress"):
                    policy.report_progress = None
        except Exception as error:
            self.store.save_decision(event_id, {"event": event, "status": "failed", "summary": str(error)})
            if not reserved:
                self.store.forget_event(event_id)
            raise
        generic = policy.event_type == "*"
        self.latest_events[event_type if generic else policy.policy_id] = evaluation_event
        if not generic and evaluation.active != was_active:
            self.store.supersede_pending(policy.policy_id)

        proposal = self._apply_evaluation(policy.policy_id, evaluation, replace_pending=not generic)
        decision = {
            "event": event,
            **(evaluation.decision or {}),
            "status": "pending" if proposal else "no_action",
            "proposal_id": proposal["id"] if proposal else None,
        }
        self.store.save_decision(event_id, decision)
        return {"duplicate": False, "event_id": event_id, "proposal": proposal, "decision": decision}

    def approve(self, proposal_id: str) -> dict[str, Any]:
        with self._event_lock:
            return self._approve(proposal_id)

    def _approve(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.store.claim(proposal_id)
        try:
            policy = next((policy for policy in self.event_policies.values()
                           if policy.policy_id == proposal["policy_id"]), None)
            if policy is None:
                raise ValueError("proposal policy is no longer registered")
            executor = getattr(policy, "execute_approved", None)
            result = (executor(proposal) if executor else
                      self.client.call_tool(proposal["tool"], proposal["arguments"]))
        except Exception as error:
            return self.store.complete(proposal_id, {"error": str(error)}, succeeded=False)
        succeeded = result.get("executed") is True
        return self.store.complete(proposal_id, result, succeeded=succeeded)

    def reject(self, proposal_id: str) -> dict[str, Any]:
        return self.store.reject(proposal_id)

    def status(self) -> dict[str, Any]:
        proposals = self.store.list_for_policies(self.policy_ids)
        return {
            "mode": "event",
            "queue": self.store.queue_status(),
            "event_types": sorted(self.event_policies),
            "latest_events": self.latest_events,
            "decisions": self.store.decisions(),
            "pending": sum(item["status"] == "pending" for item in proposals),
            "proposals": proposals,
        }

    def _apply_evaluation(
        self, policy_id: str, evaluation: PolicyEvaluation, replace_pending: bool = True
    ) -> dict[str, Any] | None:
        self.store.set_policy_active(policy_id, evaluation.active)
        if evaluation.proposal is None:
            return None
        return self.store.create(evaluation.proposal, replace_pending=replace_pending)