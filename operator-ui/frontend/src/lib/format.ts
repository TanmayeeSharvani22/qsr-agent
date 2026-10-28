// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// Display-only wording for backend data. These helpers were ported from the original
// static operator UI; they decide how values are *shown*, never what the store does.

import { isRecord } from "@/api/client";
import type { Decision, JsonObject, Proposal } from "@/api/types";

export function readable(value: unknown): string {
  const text = String(value ?? "").replace(/[_.-]+/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const STATUS_LABELS: Record<string, string> = {
  pending: "Awaiting your approval",
  no_action: "No change needed",
  queued: "Waiting to be assessed",
  processing: "Assessing event",
  executing: "Applying change",
  executed: "Completed",
  rejected: "Rejected",
  superseded: "Replaced by a newer recommendation",
  failed: "Needs review",
};

export const statusLabel = (status: string): string => STATUS_LABELS[status] ?? readable(status);

const EVENT_LABELS: Record<string, string> = {
  order_mismatch_detected: "Order issue reported",
  weather_changed: "Weather update",
  local_weather_observation_received: "Weather update",
  queue_count_changed: "Queue update",
};

export const eventLabel = (type?: string): string => (type && EVENT_LABELS[type]) || readable(type || "Store event");

const asRecord = (value: unknown): JsonObject => (isRecord(value) ? value : {});
const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

function menuItems(evidence: JsonObject): JsonObject[] {
  return Object.values(asRecord(evidence.observations))
    .flatMap((context) => asArray(asRecord(asRecord(context).menu).items))
    .filter(isRecord);
}

export function actionTitle(proposal: Proposal): string {
  const args = proposal.arguments;
  if (proposal.tool === "accuracy.request_remake") return `Remake order ${String(args.order_id ?? "")}`.trim();
  if (proposal.tool === "kiosk.change_menu_items" || proposal.tool === "change_menu_items") {
    const changes = asArray(args.changes).filter(isRecord);
    const items = menuItems(proposal.evidence);
    const labels = changes.map((change) => {
      const item = items.find((candidate) => candidate.id === change.item_id);
      return typeof item?.name === "string" ? item.name : readable(change.item_id);
    });
    const uniform = changes.length > 0 && changes.every((change) => change.available === changes[0].available);
    const prefix = uniform ? (changes[0].available ? "Make available: " : "Hide: ") : "Update menu: ";
    return prefix + labels.join(", ");
  }
  return readable(proposal.tool.split(".").pop());
}

/** One-line facts for an event, e.g. "Order 123 · Missing fries · Station 2". */
export function compactEventInfo(type: string | undefined, data: JsonObject, evidence: JsonObject): string {
  const facts: string[] = [];
  if (data.order_id !== undefined && data.order_id !== null && data.order_id !== "") {
    facts.push(`Order ${String(data.order_id)}`);
    const context = asRecord(asRecord(evidence.observations)["accuracy.get_order_accuracy_context"]);
    const order = asArray(context.recent_orders).filter(isRecord).find((item) => item.order_id === data.order_id);
    if (order) {
      const issue = asRecord(asArray(order.issues)[0]);
      if (issue.type === "missing_item") facts.push(`Missing ${readable(issue.item_id)}`);
      else if (issue.type === "wrong_item") facts.push(`${readable(issue.observed)} instead of ${readable(issue.expected)}`);
      if (order.station_id) facts.push(readable(order.station_id));
    }
  }
  if (type === "weather_changed" || type === "local_weather_observation_received") {
    if (typeof data.is_raining === "boolean") facts.push(data.is_raining ? "Rain" : "No rain");
    else if (data.condition) facts.push(readable(data.condition));
    if (typeof data.temperature_c === "number") facts.push(`${data.temperature_c} °C`);
  }
  if (type === "queue_count_changed") {
    if (typeof data.queue_count === "number") facts.push(`Queue ${data.queue_count}`);
    if (typeof data.previous_queue_count === "number") facts.push(`from ${data.previous_queue_count}`);
    if (Array.isArray(data.temporarily_hidden_items) && data.temporarily_hidden_items.length) {
      facts.push(`Restricted: ${data.temporarily_hidden_items.map(readable).join(", ")}`);
    }
  }
  if (!facts.length) {
    Object.entries(data)
      .filter(([, value]) => value === null || ["string", "number", "boolean"].includes(typeof value))
      .slice(0, 2)
      .forEach(([key, value]) => facts.push(`${readable(key)} ${String(value)}`));
  }
  const simulated = Object.values(asRecord(evidence.observations)).some((context) =>
    String(asRecord(context).source ?? "").includes("placeholder"),
  );
  if (simulated) facts.push("Demo");
  return facts.join(" · ") || eventLabel(type);
}

export const isDemoProposal = (proposal: Proposal): boolean => proposal.result?.placeholder === true;

export function proposalResultNote(proposal: Proposal): string {
  if (proposal.status === "failed") return "The change was not completed. Review the latest event before trying again.";
  const message = proposal.result?.message;
  return typeof message === "string" && message ? message : "The service confirmed the result.";
}

export function proposalContext(proposal: Proposal): string {
  const evidence = proposal.evidence;
  const eventData = asRecord(evidence.event_data);
  return compactEventInfo(typeof evidence.event_type === "string" ? evidence.event_type : undefined, eventData, evidence);
}

export function decisionContext(decision: Decision): string {
  return compactEventInfo(decision.event.event_type, decision.event.data ?? {}, decision as unknown as JsonObject);
}

export function decisionNote(decision: Decision): string {
  if (decision.status === "failed") {
    return /timed out/i.test(decision.summary ?? "")
      ? "Assessment timed out. No change was made. Submit the event again to retry."
      : "This event could not be assessed. No change was made.";
  }
  if (decision.summary) return `Hermes: ${decision.summary}`;
  return decision.status === "queued" ? "Waiting for earlier events to finish." : "Assessment in progress.";
}

/** Whole seconds since the current assessment stage began (never negative), as in the original UI. */
export const elapsedSeconds = (stageStartedAt: number, nowMs: number): number =>
  Math.max(0, Math.floor(nowMs / 1000 - stageStartedAt));
