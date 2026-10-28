// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import type { AutonomyStatus } from "@/api/types";
import { autonomySummary, buildAutonomyItems } from "./autonomy";

const base: AutonomyStatus = { ok: true, queue: {}, pending: 0, proposals: [], decisions: [] };
const proposal = (id: string, status: string, created_at: string) =>
  ({ id, status, created_at, summary: "", evidence: {}, tool: "t", arguments: {}, result: null }) as AutonomyStatus["proposals"][number];

describe("buildAutonomyItems", () => {
  it("puts items needing attention first, then newest first", () => {
    const items = buildAutonomyItems({
      ...base,
      proposals: [
        proposal("old-done", "executed", "2026-01-01T00:00:00Z"),
        proposal("new-done", "rejected", "2026-01-03T00:00:00Z"),
        proposal("pending", "pending", "2026-01-02T00:00:00Z"),
      ],
    });
    expect(items.map((item) => item.key)).toEqual(["proposal:pending", "proposal:new-done", "proposal:old-done"]);
  });
  it("skips decisions that already have a proposal and caps lists", () => {
    const decisions = Array.from({ length: 8 }, (_, i) => ({ event: { occurred_at: `2026-01-0${i + 1}T00:00:00Z`, event_type: "e" }, status: "no_action" }));
    const items = buildAutonomyItems({ ...base, decisions: [{ event: {}, status: "pending", proposal_id: "p" }, ...decisions] });
    expect(items).toHaveLength(5);
  });
  it("summarises queue state", () => {
    expect(autonomySummary({ ...base })).toBe("Events: waiting");
    expect(autonomySummary({ ...base, queue: { processing: 1, queued: 2 } })).toBe("Assessing 1 event · 2 waiting");
  });
});
