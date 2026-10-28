// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import { mockBackend, json } from "@/test/backend";
import { ApiError, ask, decideProposal, fetchServers, fetchStatus, parseAutonomyStatus } from "./client";

describe("api client", () => {
  it("parses /servers", async () => {
    mockBackend({ "/servers": () => json({ ok: true, servers: ["kiosk", "weather"], count: 2 }) });
    expect((await fetchServers()).servers).toEqual(["kiosk", "weather"]);
  });
  it("passes force=1 to /status", async () => {
    const { calls } = mockBackend({ "/status": () => json({ ok: true, services: { kiosk: { ok: true, tools: 3 } } }) });
    await fetchStatus(true);
    expect(calls[0].url).toBe("/status?force=1");
  });
  it("parses the body regardless of HTTP status, like the original fetch().json()", async () => {
    mockBackend({ "POST /ask": () => json({ ok: false, error: "bad question" }, 400) });
    expect(await ask("x")).toEqual({ ok: false, error: "bad question" });
  });
  it("sends /ask as POST {question} and uses 'unknown' when no error text is given", async () => {
    const { calls } = mockBackend({ "POST /ask": () => json({ ok: false }, 500) });
    expect(await ask("hello")).toEqual({ ok: false, error: "unknown" });
    expect(calls[0].url).toBe("/ask");
    expect(calls[0].init?.body).toBe(JSON.stringify({ question: "hello" }));
    expect((calls[0].init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
  it("propagates network and JSON errors unchanged so messages match the original", async () => {
    mockBackend({ "/servers": () => Promise.reject(new TypeError("Failed to fetch")) });
    await expect(fetchServers()).rejects.toThrow("Failed to fetch");
    mockBackend({ "/servers": () => new Response("<html>", { status: 200 }) });
    await expect(fetchServers()).rejects.toBeInstanceOf(SyntaxError);
  });
  it("treats /servers ok:false as an empty list and /status ok:false as no statuses", async () => {
    mockBackend({
      "/servers": () => json({ ok: false, error: "boom" }),
      "/status": () => json({ ok: false, services: { a: { ok: true, tools: 1 } } }),
    });
    expect((await fetchServers()).servers).toEqual([]);
    expect((await fetchStatus()).services).toEqual({});
  });
  it("rejects non-object shapes and drops junk proposals", () => {
    expect(() => parseAutonomyStatus("nope")).toThrow(ApiError);
    expect(() => parseAutonomyStatus({ ok: false, error: "x" })).toThrow("x");
    expect(parseAutonomyStatus({ ok: true, proposals: ["junk", 3] }).proposals).toEqual([]);
  });
  it("does not set any client-side timeout or abort signal", async () => {
    const { calls } = mockBackend({ "POST /ask": () => json({ ok: true, answer: "a" }) });
    await ask("q");
    expect(calls[0].init?.signal).toBeUndefined();
  });
  it("uses 'decision failed' when a rejected decision carries no error text", async () => {
    mockBackend({ "POST /autonomy/proposals/p/approve": () => json({ ok: false }, 409) });
    await expect(decideProposal("p", "approve")).rejects.toThrow("decision failed");
  });
  it("posts approve/reject to the existing endpoints with an empty object", async () => {
    const { calls } = mockBackend({
      "POST /autonomy/proposals/abc/approve": () => json({ ok: true, proposal: { id: "abc", status: "executed", summary: "", evidence: {}, tool: "t", arguments: {}, result: null } }),
    });
    const result = await decideProposal("abc", "approve");
    expect(result.proposal?.status).toBe("executed");
    expect(calls[0].init?.body).toBe("{}");
  });
  it("encodes proposal ids in the path", async () => {
    const { calls } = mockBackend({ "POST /autonomy/proposals/a%2Fb/reject": () => json({ ok: true }) });
    await decideProposal("a/b", "reject");
    expect(calls[0].url).toBe("/autonomy/proposals/a%2Fb/reject");
  });
});
