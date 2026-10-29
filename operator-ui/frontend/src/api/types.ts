// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// Response contracts of operator-ui/app.py and autonomy/store.py. Everything that
// originates from the backend, a model or an event producer is treated as untrusted:
// free-form payloads stay `unknown`/`JsonObject` and are narrowed at the point of use.

export type JsonObject = Record<string, unknown>;

export interface ServersResponse {
  ok: boolean;
  servers: string[];
  count: number;
  error?: string;
}

export interface ServiceStatus {
  ok: boolean;
  tools: number;
}

export interface StatusResponse {
  ok: boolean;
  services: Record<string, ServiceStatus>;
  error?: string;
}

export interface AutonomyQueue {
  queued?: number;
  processing?: number;
}

export interface AutonomyProgress {
  round: number;
  max_rounds: number;
  stage_started_at: number;
}

export interface AutonomyEvent {
  event_type?: string;
  occurred_at?: string;
  data?: JsonObject;
}

export interface Proposal {
  id: string;
  policy_id?: string;
  trigger_type?: string;
  summary: string;
  evidence: JsonObject;
  tool: string;
  arguments: JsonObject;
  // pending | executing | executed | rejected | superseded | failed
  status: string;
  result: JsonObject | null;
  created_at?: string;
  decided_at?: string | null;
}

export interface Decision {
  event: AutonomyEvent;
  // queued | processing | pending | no_action | failed
  status: string;
  summary?: string;
  proposal_id?: string | null;
  progress?: AutonomyProgress;
}

export interface AutonomyStatus {
  ok: boolean;
  queue: AutonomyQueue;
  pending: number;
  proposals: Proposal[];
  decisions: Decision[];
}

export interface ProposalDecisionResult {
  ok: boolean;
  proposal?: Proposal;
  error?: string;
}

export type AskAnswer = { ok: true; answer: string } | { ok: false; error: string };

/** Store event an operator chat message is linked to (the latest event, while still recent). */
export interface ActiveEvent {
  event_id: string;
  event_type?: string;
  data: JsonObject;
  age_seconds: number;
}

export interface LearnedRule {
  when: string;
  then: string;
  taught: number;
  matched: number;
  rejected: number;
  new: boolean;
}

/** A learned-skill write staged in Hermes, awaiting operator approval. */
export interface PendingSkill {
  id: string;
  skill: string;
  rules: LearnedRule[];
  removed: number;
}

export interface LearnerState {
  running: boolean;
  service: string | null;
  log: string[];
  error: string | null;
}

export interface LearningStatus {
  unlearnt_actions: number;
  pending_skill_writes: number;
  threshold: number;
  ready: { service: string; count: number }[];
  pending: PendingSkill[];
  learner: LearnerState;
  active_event: ActiveEvent | null;
}
