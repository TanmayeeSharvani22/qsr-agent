from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ProposedAction


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ProposalStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    policy_id TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT
                );
                CREATE TABLE IF NOT EXISTS policy_state (
                    policy_id TEXT PRIMARY KEY,
                    active INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS received_events (
                    event_id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_decisions (
                    event_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_queue (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_json TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def enqueue_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_id = event["event_id"]
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT status FROM event_queue WHERE event_id = ?", (event_id,)
            ).fetchone()
            received = self._connection.execute(
                "SELECT 1 FROM received_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if received or (existing and existing["status"] != "failed"):
                return {"event_id": event_id, "duplicate": True,
                        "status": existing["status"] if existing else "completed"}
            self._connection.execute("DELETE FROM event_queue WHERE event_id = ?", (event_id,))
            self._connection.execute(
                "INSERT INTO event_queue (event_id, event_json, status) VALUES (?, ?, 'queued')",
                (event_id, json.dumps(event)),
            )
            self._connection.execute(
                "INSERT INTO received_events VALUES (?, ?)", (event_id, _now())
            )
            self._connection.execute(
                "INSERT INTO event_decisions VALUES (?, ?, ?) ON CONFLICT(event_id) "
                "DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (event_id, json.dumps({"event": event, "status": "queued"}), _now()),
            )
        return {"event_id": event_id, "duplicate": False, "status": "queued"}

    def recover_events(self) -> None:
        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT event_id, event_json FROM event_queue WHERE status = 'processing'"
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    "UPDATE event_decisions SET payload_json = ?, updated_at = ? WHERE event_id = ?",
                    (json.dumps({"event": json.loads(row["event_json"]), "status": "queued"}),
                     _now(), row["event_id"]),
                )
            self._connection.execute("UPDATE event_queue SET status = 'queued' WHERE status = 'processing'")

    def claim_event(self) -> dict[str, Any] | None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT event_id, event_json FROM event_queue WHERE status = 'queued' ORDER BY sequence LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._connection.execute(
                "UPDATE event_queue SET status = 'processing' WHERE event_id = ?", (row["event_id"],)
            )
            event = json.loads(row["event_json"])
            self._connection.execute(
                "UPDATE event_decisions SET payload_json = ?, updated_at = ? WHERE event_id = ?",
                (json.dumps({"event": event, "status": "processing"}), _now(), row["event_id"]),
            )
        return event

    def finish_event(self, event: dict[str, Any], error: str | None = None) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE event_queue SET status = ? WHERE event_id = ?",
                ("failed" if error is not None else "completed", event["event_id"]),
            )
            if error is not None:
                self._connection.execute("DELETE FROM received_events WHERE event_id = ?", (event["event_id"],))
                self._connection.execute(
                    "UPDATE event_decisions SET payload_json = ?, updated_at = ? WHERE event_id = ?",
                    (json.dumps({"event": event, "status": "failed", "summary": error}), _now(), event["event_id"]),
                )

    def queue_status(self) -> dict[str, int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT status, COUNT(*) AS count FROM event_queue GROUP BY status"
            ).fetchall()
        counts = {row["status"]: row["count"] for row in rows}
        return {status: counts.get(status, 0) for status in ("queued", "processing")}

    def is_policy_active(self, policy_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT active FROM policy_state WHERE policy_id = ?", (policy_id,)
            ).fetchone()
        return bool(row["active"]) if row else False

    def set_policy_active(self, policy_id: str, active: bool) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO policy_state (policy_id, active, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (policy_id, int(active), _now()),
            )

    def record_event(self, event_id: str) -> bool:
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT INTO received_events (event_id, received_at) VALUES (?, ?)",
                    (event_id, _now()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def forget_event(self, event_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM received_events WHERE event_id = ?", (event_id,)
            )

    def save_decision(self, event_id: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO event_decisions VALUES (?, ?, ?) ON CONFLICT(event_id) "
                "DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (event_id, json.dumps(payload), _now()),
            )

    def decisions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload_json FROM event_decisions ORDER BY updated_at DESC LIMIT 30"
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def create(self, proposed: ProposedAction, replace_pending: bool = True) -> dict[str, Any]:
        proposal_id = f"proposal-{uuid.uuid4().hex}"
        created_at = _now()
        with self._lock, self._connection:
            pending = self._connection.execute(
                "SELECT * FROM proposals WHERE policy_id = ? AND status = 'pending'",
                (proposed.policy_id,),
            ).fetchall()
            for row in pending:
                existing = self._decode(row)
                if (
                    existing["tool"] == proposed.tool
                    and existing["arguments"] == proposed.arguments
                ):
                    return existing
            if pending and replace_pending:
                self._connection.execute(
                    """
                    UPDATE proposals SET status = 'superseded', decided_at = ?
                    WHERE policy_id = ? AND status = 'pending'
                    """,
                    (created_at, proposed.policy_id),
                )
            self._connection.execute(
                """
                INSERT INTO proposals (
                    id, policy_id, trigger_type, summary, evidence_json, tool,
                    arguments_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    proposal_id,
                    proposed.policy_id,
                    proposed.trigger_type,
                    proposed.summary,
                    json.dumps(proposed.evidence, separators=(",", ":")),
                    proposed.tool,
                    json.dumps(proposed.arguments, separators=(",", ":")),
                    created_at,
                ),
            )
        return self.get(proposal_id)

    def get(self, proposal_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        return self._decode(row)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode(row) for row in rows]

    def list_for_policies(
        self, policy_ids: set[str], limit: int = 50
    ) -> list[dict[str, Any]]:
        if not policy_ids:
            return []
        placeholders = ",".join("?" for _ in policy_ids)
        parameters = (*sorted(policy_ids), limit)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT * FROM proposals WHERE policy_id IN ({placeholders})
                ORDER BY created_at DESC LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._decode(row) for row in rows]

    def supersede_unregistered(self, policy_ids: set[str]) -> int:
        with self._lock, self._connection:
            if policy_ids:
                placeholders = ",".join("?" for _ in policy_ids)
                query = f"""
                    UPDATE proposals SET status = 'superseded', decided_at = ?
                    WHERE status = 'pending' AND policy_id NOT IN ({placeholders})
                """
                parameters = (_now(), *sorted(policy_ids))
            else:
                query = """
                    UPDATE proposals SET status = 'superseded', decided_at = ?
                    WHERE status = 'pending'
                """
                parameters = (_now(),)
            cursor = self._connection.execute(query, parameters)
        return cursor.rowcount

    def claim(self, proposal_id: str) -> dict[str, Any]:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE proposals SET status = 'executing', decided_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (_now(), proposal_id),
            )
        if cursor.rowcount != 1:
            proposal = self.get(proposal_id)
            raise ValueError(f"proposal is {proposal['status']}")
        return self.get(proposal_id)

    def complete(self, proposal_id: str, result: dict[str, Any], succeeded: bool) -> dict[str, Any]:
        status = "executed" if succeeded else "failed"
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE proposals SET status = ?, result_json = ?, decided_at = ? WHERE id = ?",
                (status, json.dumps(result, separators=(",", ":")), _now(), proposal_id),
            )
        return self.get(proposal_id)

    def reject(self, proposal_id: str) -> dict[str, Any]:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE proposals SET status = 'rejected', decided_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (_now(), proposal_id),
            )
        if cursor.rowcount != 1:
            proposal = self.get(proposal_id)
            raise ValueError(f"proposal is {proposal['status']}")
        return self.get(proposal_id)

    def supersede_pending(self, policy_id: str) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE proposals SET status = 'superseded', decided_at = ?
                WHERE policy_id = ? AND status = 'pending'
                """,
                (_now(), policy_id),
            )
        return cursor.rowcount

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "policy_id": row["policy_id"],
            "trigger_type": row["trigger_type"],
            "summary": row["summary"],
            "evidence": json.loads(row["evidence_json"]),
            "tool": row["tool"],
            "arguments": json.loads(row["arguments_json"]),
            "status": row["status"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": row["created_at"],
            "decided_at": row["decided_at"],
        }