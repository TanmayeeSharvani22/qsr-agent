// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import type { AutonomyStatus, Decision, Proposal } from "@/api/types";
import { eventLabel, statusLabel } from "./format";

export type AutonomyItem =
  | { kind: "proposal"; key: string; priority: number; timestamp: number; proposal: Proposal }
  | { kind: "decision"; key: string; priority: number; timestamp: number; decision: Decision };

const ATTENTION = new Set(["pending", "processing", "queued", "failed", "executing"]);
const priorityOf = (status: string) => (ATTENTION.has(status) ? 0 : 1);
const MAX_PROPOSALS = 10;
const MAX_DECISIONS = 5;

/**
 * Same ordering the original UI used: items needing attention first, then newest first.
 * Up to 10 proposals plus up to 5 events that did not produce a proposal.
 */
export function buildAutonomyItems(data: AutonomyStatus): AutonomyItem[] {
  const proposals: AutonomyItem[] = data.proposals
    .slice()
    .sort((a, b) => priorityOf(a.status) - priorityOf(b.status))
    .slice(0, MAX_PROPOSALS)
    .map((proposal) => ({
      kind: "proposal",
      key: `proposal:${proposal.id}`,
      priority: priorityOf(proposal.status),
      timestamp: Date.parse(proposal.created_at ?? "") || 0,
      proposal,
    }));
  const decisions: AutonomyItem[] = data.decisions
    .filter((decision) => !decision.proposal_id)
    .sort((a, b) => priorityOf(a.status) - priorityOf(b.status))
    .slice(0, MAX_DECISIONS)
    .map((decision, index) => ({
      kind: "decision",
      key: `decision:${decision.event.occurred_at ?? ""}:${decision.event.event_type ?? ""}:${index}`,
      priority: priorityOf(decision.status),
      timestamp: Date.parse(decision.event.occurred_at ?? "") || 0,
      decision,
    }));
  return [...proposals, ...decisions].sort((a, b) => a.priority - b.priority || b.timestamp - a.timestamp);
}

/** The one-line summary shown under the panel title. */
export function autonomySummary(data: AutonomyStatus): string {
  const queue = data.queue;
  if (queue.processing || queue.queued) {
    return (
      (queue.processing ? "Assessing 1 event" : "Waiting for assessment") +
      (queue.queued ? ` · ${queue.queued} waiting` : "")
    );
  }
  const latest = data.decisions[0];
  return latest ? `${eventLabel(latest.event.event_type)} · ${statusLabel(latest.status)}` : "Events: waiting";
}
