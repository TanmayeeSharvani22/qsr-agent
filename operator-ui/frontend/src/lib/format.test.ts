// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import type { Proposal } from "@/api/types";
import { actionTitle, compactEventInfo, decisionNote, eventLabel, readable, statusLabel } from "./format";

describe("format helpers", () => {
  it("humanises identifiers", () => {
    expect(readable("order_mismatch.detected")).toBe("Order mismatch detected");
    expect(readable(null)).toBe("");
  });
  it("maps statuses and events, falling back to readable text", () => {
    expect(statusLabel("pending")).toBe("Awaiting your approval");
    expect(statusLabel("weird_state")).toBe("Weird state");
    expect(eventLabel("queue_count_changed")).toBe("Queue update");
    expect(eventLabel(undefined)).toBe("Store event");
  });
  it("titles menu proposals", () => {
    const hide = { tool: "kiosk.change_menu_items", arguments: { changes: [{ item_id: "fries", available: false }] }, evidence: {} } as unknown as Proposal;
    expect(actionTitle(hide)).toBe("Hide: Fries");
    const remake = { tool: "accuracy.request_remake", arguments: { order_id: "42" }, evidence: {} } as unknown as Proposal;
    expect(actionTitle(remake)).toBe("Remake order 42");
  });
  it("summarises queue events and flags demo data", () => {
    const text = compactEventInfo("queue_count_changed", { queue_count: 9, previous_queue_count: 3 }, { observations: { k: { source: "placeholder" } } });
    expect(text).toBe("Queue 9 · from 3 · Demo");
  });
  it("tolerates garbage payloads", () => {
    expect(compactEventInfo("weather_changed", {}, { observations: "nope" })).toBe("Weather update");
  });
  it("explains failed decisions", () => {
    const base = { event: {}, status: "failed" } as const;
    expect(decisionNote({ ...base, summary: "Hermes timed out" })).toMatch(/timed out/);
    expect(decisionNote({ ...base })).toMatch(/could not be assessed/);
  });
});
