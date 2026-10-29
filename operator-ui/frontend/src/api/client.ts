// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import type {
  ActiveEvent,
  AskAnswer,
  AutonomyStatus,
  Decision,
  JsonObject,
  LearnedRule,
  LearningStatus,
  PendingSkill,
  Proposal,
  ProposalDecisionResult,
  ServersResponse,
  StatusResponse,
} from "./types";

// Same-origin only: the Python server serves both the UI and the API, so no base URL,
// credentials or CORS configuration is needed (or wanted) in the frontend.

export type ApiErrorKind = "malformed" | "backend";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

export const isRecord = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  signal?: AbortSignal;
}

/**
 * Fetch JSON from the backend exactly as the original UI did: the body is parsed whatever the
 * HTTP status (the backend reports failures as `{ok:false,error}`), and there is no client-side
 * timeout, retry or cancellation other than the caller's own signal.
 */
export async function requestJson(path: string, options: RequestOptions = {}): Promise<unknown> {
  const { method = "GET", body, signal } = options;
  // Network and JSON-parse failures propagate unchanged so callers print the same
  // "TypeError: Failed to fetch" style text the original UI showed.
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  return response.json();
}

const asNumber = (value: unknown, fallback = 0) => (typeof value === "number" && Number.isFinite(value) ? value : fallback);

export function parseServers(payload: unknown): ServersResponse {
  if (!isRecord(payload)) {
    throw new ApiError("malformed", "The server returned an unexpected services response.");
  }
  // The original UI treated `ok:false` (or a missing list) as "no services".
  const servers = payload.ok === true && Array.isArray(payload.servers)
    ? payload.servers.filter((name): name is string => typeof name === "string")
    : [];
  return {
    ok: payload.ok === true,
    servers,
    count: asNumber(payload.count, servers.length),
    error: typeof payload.error === "string" ? payload.error : undefined,
  };
}

export function parseStatus(payload: unknown): StatusResponse {
  if (!isRecord(payload)) {
    throw new ApiError("malformed", "The server returned an unexpected status response.");
  }
  const services: StatusResponse["services"] = {};
  if (payload.ok === true && isRecord(payload.services)) {
    for (const [name, value] of Object.entries(payload.services)) {
      if (isRecord(value)) services[name] = { ok: value.ok === true, tools: asNumber(value.tools) };
    }
  }
  return {
    ok: payload.ok === true,
    services,
    error: typeof payload.error === "string" ? payload.error : undefined,
  };
}

function parseProposal(value: unknown): Proposal | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.tool !== "string") return null;
  return {
    id: value.id,
    policy_id: typeof value.policy_id === "string" ? value.policy_id : undefined,
    trigger_type: typeof value.trigger_type === "string" ? value.trigger_type : undefined,
    summary: typeof value.summary === "string" ? value.summary : "",
    evidence: isRecord(value.evidence) ? value.evidence : {},
    tool: value.tool,
    arguments: isRecord(value.arguments) ? value.arguments : {},
    status: typeof value.status === "string" ? value.status : "unknown",
    result: isRecord(value.result) ? value.result : null,
    created_at: typeof value.created_at === "string" ? value.created_at : undefined,
    decided_at: typeof value.decided_at === "string" ? value.decided_at : null,
  };
}

function parseDecision(value: unknown): Decision | null {
  if (!isRecord(value) || !isRecord(value.event)) return null;
  const progress = isRecord(value.progress)
    ? {
        round: asNumber(value.progress.round),
        max_rounds: asNumber(value.progress.max_rounds),
        stage_started_at: asNumber(value.progress.stage_started_at),
      }
    : undefined;
  return {
    event: {
      event_type: typeof value.event.event_type === "string" ? value.event.event_type : undefined,
      occurred_at: typeof value.event.occurred_at === "string" ? value.event.occurred_at : undefined,
      data: isRecord(value.event.data) ? value.event.data : {},
    },
    status: typeof value.status === "string" ? value.status : "unknown",
    summary: typeof value.summary === "string" ? value.summary : undefined,
    proposal_id: typeof value.proposal_id === "string" ? value.proposal_id : null,
    progress,
  };
}

export function parseAutonomyStatus(payload: unknown): AutonomyStatus {
  if (!isRecord(payload) || payload.ok !== true) {
    const message = isRecord(payload) && typeof payload.error === "string" ? payload.error : "Autonomy unavailable";
    throw new ApiError("backend", message);
  }
  const queue = isRecord(payload.queue)
    ? { queued: asNumber(payload.queue.queued), processing: asNumber(payload.queue.processing) }
    : {};
  const proposals = (Array.isArray(payload.proposals) ? payload.proposals : [])
    .map(parseProposal)
    .filter((item): item is Proposal => item !== null);
  const decisions = (Array.isArray(payload.decisions) ? payload.decisions : [])
    .map(parseDecision)
    .filter((item): item is Decision => item !== null);
  return { ok: true, queue, pending: asNumber(payload.pending), proposals, decisions };
}

export function parseProposalDecision(payload: unknown): ProposalDecisionResult {
  if (!isRecord(payload)) {
    throw new ApiError("malformed", "The server returned an unexpected response.");
  }
  if (!payload.ok) {
    throw new ApiError("backend", typeof payload.error === "string" && payload.error ? payload.error : "decision failed");
  }
  return { ok: true, proposal: parseProposal(payload.proposal) ?? undefined };
}

export function parseAsk(payload: unknown): AskAnswer {
  if (!isRecord(payload)) {
    throw new ApiError("malformed", "The server returned an unexpected answer.");
  }
  if (payload.ok && typeof payload.answer === "string") return { ok: true, answer: payload.answer };
  return { ok: false, error: typeof payload.error === "string" && payload.error ? payload.error : "unknown" };
}

export async function fetchServers(signal?: AbortSignal): Promise<ServersResponse> {
  return parseServers(await requestJson("/servers", { signal }));
}

export async function fetchStatus(force = false, signal?: AbortSignal): Promise<StatusResponse> {
  return parseStatus(await requestJson(force ? "/status?force=1" : "/status", { signal }));
}

export async function fetchAutonomyStatus(signal?: AbortSignal): Promise<AutonomyStatus> {
  return parseAutonomyStatus(await requestJson("/autonomy/status", { signal }));
}

export async function decideProposal(
  proposalId: string,
  decision: "approve" | "reject",
  reason = "",
  signal?: AbortSignal,
): Promise<ProposalDecisionResult> {
  const path = `/autonomy/proposals/${encodeURIComponent(proposalId)}/${decision}`;
  return parseProposalDecision(await requestJson(path, { method: "POST", body: reason ? { reason } : {}, signal }));
}

/** `eventId` links the message to a recent store event so the operator's instruction is learnt. */
export async function ask(question: string, eventId?: string, signal?: AbortSignal): Promise<AskAnswer> {
  const body = eventId ? { question, event_id: eventId } : { question };
  return parseAsk(await requestJson("/ask", { method: "POST", body, signal }));
}

/** Start a fresh Hermes conversation; Hermes memory is kept. */
export async function newChat(): Promise<void> {
  const payload = await requestJson("/chat/new", { method: "POST", body: {} });
  if (!isRecord(payload) || payload.ok !== true) {
    throw new ApiError("backend", isRecord(payload) && typeof payload.error === "string" ? payload.error : "could not start a new chat");
  }
}

const asString = (value: unknown, fallback = "") => (typeof value === "string" ? value : fallback);

function parseRule(value: unknown): LearnedRule | null {
  if (!isRecord(value)) return null;
  return {
    when: asString(value.when),
    then: asString(value.then),
    taught: asNumber(value.taught),
    matched: asNumber(value.matched),
    rejected: asNumber(value.rejected),
    new: value.new === true,
  };
}

function parsePending(value: unknown): PendingSkill | null {
  if (!isRecord(value) || typeof value.id !== "string") return null;
  const rules = (Array.isArray(value.rules) ? value.rules : []).map(parseRule).filter((rule): rule is LearnedRule => rule !== null);
  return { id: value.id, skill: asString(value.skill, "learned skill"), rules, removed: asNumber(value.removed) };
}

function parseActiveEvent(value: unknown): ActiveEvent | null {
  if (!isRecord(value) || typeof value.event_id !== "string") return null;
  return {
    event_id: value.event_id,
    event_type: typeof value.event_type === "string" ? value.event_type : undefined,
    data: isRecord(value.data) ? value.data : {},
    age_seconds: asNumber(value.age_seconds),
  };
}

export function parseLearningStatus(payload: unknown): LearningStatus {
  if (!isRecord(payload) || payload.ok !== true) {
    throw new ApiError("backend", "learning unavailable");
  }
  const learner = isRecord(payload.learner) ? payload.learner : {};
  return {
    unlearnt_actions: asNumber(payload.unlearnt_actions),
    pending_skill_writes: asNumber(payload.pending_skill_writes),
    threshold: asNumber(payload.threshold),
    ready: (Array.isArray(payload.ready) ? payload.ready : [])
      .filter(isRecord)
      .filter((item) => typeof item.service === "string")
      .map((item) => ({ service: item.service as string, count: asNumber(item.count) })),
    pending: (Array.isArray(payload.pending) ? payload.pending : [])
      .map(parsePending)
      .filter((item): item is PendingSkill => item !== null),
    learner: {
      running: learner.running === true,
      service: typeof learner.service === "string" ? learner.service : null,
      log: (Array.isArray(learner.log) ? learner.log : []).filter((line): line is string => typeof line === "string"),
      error: typeof learner.error === "string" ? learner.error : null,
    },
    active_event: parseActiveEvent(payload.active_event),
  };
}

export async function fetchLearningStatus(signal?: AbortSignal): Promise<LearningStatus> {
  return parseLearningStatus(await requestJson("/learning/status", { signal }));
}

async function postLearning(path: string, body: unknown, failure: string): Promise<void> {
  const payload = await requestJson(path, { method: "POST", body });
  if (!isRecord(payload) || payload.ok !== true) {
    throw new ApiError("backend", isRecord(payload) && typeof payload.error === "string" && payload.error ? payload.error : failure);
  }
}

export const startLearning = (service: string) => postLearning("/learning/run", { service }, "could not start learning");

export const decideSkill = (pendingId: string, decision: "approve" | "reject") =>
  postLearning(`/learning/pending/${encodeURIComponent(pendingId)}/${decision}`, {}, "decision failed");
