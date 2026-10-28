// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { vi } from "vitest";

type Handler = (init: RequestInit | undefined, url: string) => Response | Promise<Response>;

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Stub global fetch with per-path handlers; unknown paths fail the test loudly. */
export function mockBackend(routes: Record<string, Handler>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const path = url.split("?")[0];
    const handler = routes[`${init?.method ?? "GET"} ${path}`] ?? routes[path];
    if (!handler) throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
    return handler(init, url);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export const emptyAutonomy = {
  ok: true,
  mode: "approval",
  queue: { queued: 0, processing: 0 },
  event_types: [],
  latest_events: [],
  decisions: [],
  pending: 0,
  proposals: [],
};

export const proposal = (overrides: Record<string, unknown> = {}) => ({
  id: "p1",
  policy_id: "x",
  summary: "Hide fries during rush",
  evidence: { event_type: "queue_count_changed", event_data: { queue_count: 12, previous_queue_count: 4 }, observations: {} },
  tool: "kiosk.change_menu_items",
  arguments: { changes: [{ item_id: "fries", available: false }] },
  status: "pending",
  result: null,
  created_at: "2026-01-01T10:00:00Z",
  ...overrides,
});
