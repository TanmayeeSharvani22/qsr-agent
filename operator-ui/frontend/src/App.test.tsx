// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ThemeProvider } from "./hooks/use-theme";
import { emptyAutonomy, json, mockBackend, proposal } from "./test/backend";

const servers = () => json({ ok: true, servers: ["kiosk", "weather", "accuracy"], count: 3 });
const status = () => json({ ok: true, services: { kiosk: { ok: true, tools: 4 }, weather: { ok: false, tools: 0 } } });

const renderApp = () =>
  render(
    <ThemeProvider>
      <App />
    </ThemeProvider>,
  );

describe("App", () => {
  it("renders all panels with service states", async () => {
    mockBackend({ "/servers": servers, "/status": status, "/autonomy/status": () => json(emptyAutonomy) });
    renderApp();
    expect(screen.getByRole("heading", { name: "QSR Store Agent" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Operator Chat" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Autonomy Decisions" })).toBeInTheDocument();
    expect(await screen.findByText("4 tools")).toBeInTheDocument();
    expect(screen.getByText("kiosk: Online.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("weather: Offline.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("accuracy: Status not known", { exact: false })).toBeInTheDocument(); // absent from /status: neutral, no text
    expect(await screen.findByText("No decisions yet")).toBeInTheDocument();
  });

  it("shows the original unavailable texts when /servers and /autonomy/status fail", async () => {
    mockBackend({
      "/servers": () => Promise.reject(new TypeError("down")),
      "/autonomy/status": () => Promise.reject(new TypeError("down")),
    });
    renderApp();
    expect(await screen.findByText("Status unavailable")).toBeInTheDocument();
    expect(await screen.findByText("Autonomy unavailable", { selector: "p[role=alert]" })).toBeInTheDocument();
  });

  it("shows /servers ok:false as 'No services connected' and ignores the error text", async () => {
    mockBackend({ "/servers": () => json({ ok: false, error: "hermes missing" }), "/autonomy/status": () => json(emptyAutonomy) });
    renderApp();
    expect(await screen.findByText("No services connected")).toBeInTheDocument();
    expect(screen.queryByText("hermes missing")).toBeNull();
  });

  it("uses a generic 'Autonomy unavailable' even when the backend sends an error text", async () => {
    mockBackend({ "/servers": servers, "/status": status, "/autonomy/status": () => json({ ok: false, error: "secret detail" }, 500) });
    renderApp();
    expect(await screen.findByText("Autonomy unavailable", { selector: "p[role=alert]" })).toBeInTheDocument();
    expect(screen.queryByText("secret detail")).toBeNull();
  });

  const baseRoutes = () => ({ "/servers": servers, "/status": status, "/autonomy/status": () => json(emptyAutonomy) });
  const sendQuestion = async (text: string) => {
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Ask the store agent"), `${text}{Enter}`);
  };

  it("chat posts {question} to /ask only and renders the answer as plain text", async () => {
    const { calls } = mockBackend({
      ...baseRoutes(),
      "POST /ask": () => json({ ok: true, answer: "<img src=x onerror=alert(1)> done" }),
    });
    renderApp();
    await sendQuestion("  hello  ");
    const log = screen.getByRole("log");
    await waitFor(() => expect(within(log).getByText(/onerror=alert\(1\)/)).toBeInTheDocument());
    expect(log.querySelector("img")).toBeNull();
    const asks = calls.filter((c) => c.url.startsWith("/ask"));
    expect(asks.map((c) => c.url)).toEqual(["/ask"]);
    expect(asks[0].init?.body).toBe(JSON.stringify({ question: "hello" }));
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
  });

  it("shows 'thinking…' while waiting and disables Send", async () => {
    let release: (value: Response) => void = () => {};
    mockBackend({ ...baseRoutes(), "POST /ask": () => new Promise<Response>((resolve) => (release = resolve)) });
    renderApp();
    await sendQuestion("hi");
    expect(await screen.findByText("thinking…", { selector: "span[role=status]" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
    await act(async () => release(json({ ok: true, answer: "ok" })));
    expect(await screen.findByText("ok")).toBeInTheDocument();
  });

  it("shows 'Error: <error>' or 'Error: unknown' for ok:false answers (any HTTP status)", async () => {
    mockBackend({ ...baseRoutes(), "POST /ask": () => json({ ok: false, error: "model offline" }, 500) });
    const first = renderApp();
    await sendQuestion("hi");
    expect(await screen.findByText("Error: model offline")).toBeInTheDocument();
    first.unmount();
    mockBackend({ ...baseRoutes(), "POST /ask": () => json({ ok: false }) });
    renderApp();
    await sendQuestion("hi");
    expect(await screen.findByText("Error: unknown")).toBeInTheDocument();
  });

  it("shows 'Request failed: <err>' on network errors and never retries or streams", async () => {
    const { calls } = mockBackend({ ...baseRoutes(), "POST /ask": () => Promise.reject(new TypeError("Failed to fetch")) });
    renderApp();
    await sendQuestion("hi");
    expect(await screen.findByText("Request failed: TypeError: Failed to fetch")).toBeInTheDocument();
    expect(calls.filter((c) => c.url.startsWith("/ask")).length).toBe(1);
    expect(calls.some((c) => c.url.includes("stream"))).toBe(false);
  });

  it("suggestion chips only fill the input", async () => {
    const { calls } = mockBackend({ "/servers": servers, "/status": status, "/autonomy/status": () => json(emptyAutonomy) });
    renderApp();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "How deep is the kiosk queue?" }));
    expect(screen.getByLabelText("Ask the store agent")).toHaveValue("How deep is the kiosk queue?");
    expect(calls.some((c) => c.url.startsWith("/ask"))).toBe(false);
  });

  it("displays proposal statuses with the original wording and approves through the existing endpoint", async () => {
    const approved = proposal({ status: "executed" });
    let approvedYet = false;
    const { calls } = mockBackend({
      "/servers": servers,
      "/status": status,
      "/autonomy/status": () =>
        json({
          ...emptyAutonomy,
          pending: 1,
          proposals: [
            proposal(),
            proposal({ id: "p2", status: "failed", summary: "<b>x</b>", result: { message: "ignored" } }),
            proposal({ id: "p3", status: "executed", result: { placeholder: true, message: "Menu updated" } }),
            proposal({ id: "p4", status: "executed", result: {} }),
          ],
        }),
      "POST /autonomy/proposals/p1/approve": () => {
        approvedYet = true;
        return json({ ok: true, proposal: approved });
      },
    });
    renderApp();
    expect(await screen.findByText("Awaiting your approval")).toBeInTheDocument();
    expect(screen.getByText("Hermes: Hide fries during rush")).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("The change was not completed. Review the latest event before trying again.")).toBeInTheDocument();
    expect(screen.getByText("Menu updated")).toBeInTheDocument();
    expect(screen.getByText("The service confirmed the result.")).toBeInTheDocument();
    expect(screen.getByText("Demo · simulated action")).toBeInTheDocument();
    expect(screen.queryByText("<b>x</b>")).toBeNull(); // summary is only shown for pending proposals
    const countBefore = calls.filter((c) => c.url === "/autonomy/status").length;
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Approve: Hide: Fries/ }));
    await waitFor(() => expect(approvedYet).toBe(true));
    const post = calls.find((c) => c.url === "/autonomy/proposals/p1/approve");
    expect(post?.init?.method).toBe("POST");
    expect(post?.init?.body).toBe("{}");
    // a successful decision reloads the autonomy list
    await waitFor(() => expect(calls.filter((c) => c.url === "/autonomy/status").length).toBeGreaterThan(countBefore));
  });

  it("reports a failed decision as a chat error bubble and does not reload the list", async () => {
    const { calls } = mockBackend({
      "/servers": servers,
      "/status": status,
      "/autonomy/status": () => json({ ...emptyAutonomy, pending: 1, proposals: [proposal()] }),
      "POST /autonomy/proposals/p1/reject": () => json({ ok: false, error: "proposal is executed" }, 409),
    });
    renderApp();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Reject: / }));
    const log = screen.getByRole("log");
    expect(await within(log).findByText("Autonomy action failed: Error: proposal is executed")).toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/autonomy/status").length).toBe(1);
  });

  it("uses 'decision failed' in the chat error when the backend gives no text", async () => {
    mockBackend({
      "/servers": servers,
      "/status": status,
      "/autonomy/status": () => json({ ...emptyAutonomy, pending: 1, proposals: [proposal()] }),
      "POST /autonomy/proposals/p1/approve": () => json({ ok: false }, 500),
    });
    renderApp();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Approve: / }));
    expect(await within(screen.getByRole("log")).findByText("Autonomy action failed: Error: decision failed")).toBeInTheDocument();
  });

  it("orders attention items first, then newest, capped at 10 proposals and 5 decisions", async () => {
    const proposals = Array.from({ length: 12 }, (_, i) =>
      proposal({ id: `e${i}`, status: "executed", result: { message: `m${i}` }, created_at: `2026-01-01T10:${String(i).padStart(2, "0")}:00Z` }),
    );
    proposals.push(proposal({ id: "old-pending", created_at: "2025-01-01T00:00:00Z" }));
    const decisions = Array.from({ length: 7 }, (_, i) => ({
      event: { event_type: "weather_changed", occurred_at: `2026-02-01T10:0${i}:00Z`, data: { is_raining: true } },
      status: "no_action",
    }));
    decisions.push({ event: { event_type: "queue_count_changed", occurred_at: "2020-01-01T00:00:00Z", data: {} }, status: "queued", proposal_id: "p" } as never);
    mockBackend({ ...baseRoutes(), "/autonomy/status": () => json({ ...emptyAutonomy, pending: 1, proposals, decisions }) });
    renderApp();
    await screen.findAllByTestId("proposal");
    expect(screen.getAllByTestId("proposal").length).toBe(10);
    expect(screen.getAllByTestId("decision").length).toBe(5);
    const first = screen.getAllByTestId("proposal")[0];
    expect(first).toHaveAttribute("data-status", "pending");
    const all = [...document.querySelectorAll("[data-testid=proposal],[data-testid=decision]")];
    expect(all[0]).toBe(first);
    expect(all[1]).toHaveAttribute("data-testid", "decision"); // 2026-02 decisions are newer than 2026-01 proposals
  });

  it("shows the awaiting count, summary line and the assessment step line", async () => {
    const started = Date.now() / 1000 - 12;
    mockBackend({
      ...baseRoutes(),
      "/autonomy/status": () =>
        json({
          ...emptyAutonomy,
          pending: 3,
          queue: { queued: 2, processing: 1 },
          decisions: [
            { event: { event_type: "queue_count_changed", occurred_at: "2026-01-01T00:00:00Z", data: { queue_count: 9 } }, status: "processing", progress: { round: 2, max_rounds: 5, stage_started_at: started } },
          ],
        }),
    });
    renderApp();
    expect(await screen.findByText("Assessing 1 event · 2 waiting")).toBeInTheDocument();
    expect(screen.getByLabelText("Awaiting approval")).toHaveTextContent("3");
    expect(screen.getByText("Assessment in progress.")).toBeInTheDocument();
    expect(screen.getByText(/Assessing · Step 2 of 5 · 1[0-9]s/)).toBeInTheDocument();
  });

  describe("polling and refresh", () => {
    afterEach(() => vi.useRealTimers());

    it("polls /status every 30s and /autonomy/status every 5s, and Refresh forces /status?force=1", async () => {
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
      const { calls } = mockBackend(baseRoutes());
      renderApp();
      await screen.findByText("4 tools");
      const count = (url: string) => calls.filter((c) => c.url === url).length;
      const statusBefore = count("/status");
      const autonomyBefore = count("/autonomy/status");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(count("/autonomy/status")).toBe(autonomyBefore + 1);
      expect(count("/status")).toBe(statusBefore);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(25000);
      });
      expect(count("/status")).toBe(statusBefore + 1);
      expect(count("/autonomy/status")).toBe(autonomyBefore + 6);
      vi.useRealTimers();
      await userEvent.setup().click(screen.getByRole("button", { name: /Refresh services/ }));
      await waitFor(() => expect(count("/status?force=1")).toBe(1));
      expect(count("/servers")).toBe(2);
    });
  });
  it("toggles the theme and persists it", async () => {
    mockBackend({ "/servers": servers, "/status": status, "/autonomy/status": () => json(emptyAutonomy) });
    renderApp();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("qsr-theme")).toBe("dark");
    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement).not.toHaveClass("dark");
    expect(localStorage.getItem("qsr-theme")).toBe("light");
  });

  it("restores a stored theme", () => {
    localStorage.setItem("qsr-theme", "dark");
    mockBackend({ "/servers": servers, "/status": status, "/autonomy/status": () => json(emptyAutonomy) });
    renderApp();
    expect(document.documentElement).toHaveClass("dark");
  });

  it("is keyboard operable: skip link and labelled controls", async () => {
    mockBackend({ "/servers": servers, "/status": status, "/autonomy/status": () => json(emptyAutonomy) });
    renderApp();
    expect(screen.getByRole("link", { name: "Skip to chat" })).toHaveAttribute("href", "#chat-title");
    expect(screen.getByRole("button", { name: /Refresh services/ })).toBeInTheDocument();
    expect(screen.getAllByRole("complementary").length).toBeGreaterThan(0);
    await screen.findByText("4 tools");
  });

  const learning = (overrides: Record<string, unknown> = {}) => ({
    ok: true,
    unlearnt_actions: 0,
    pending_skill_writes: 0,
    threshold: 20,
    ready: [],
    pending: [],
    learner: { running: false, service: null, log: [], error: null },
    active_event: null,
    ...overrides,
  });

  it("New chat starts a fresh Hermes conversation and clears the transcript", async () => {
    const { calls } = mockBackend({
      ...baseRoutes(),
      "/learning/status": () => json(learning()),
      "POST /ask": () => json({ ok: true, answer: "2 customers" }),
      "POST /chat/new": () => json({ ok: true }),
    });
    renderApp();
    await sendQuestion("queue?");
    expect(await screen.findByText("2 customers")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /New chat/ }));
    await waitFor(() => expect(screen.queryByText("2 customers")).toBeNull());
    expect(calls.some((c) => c.url === "/chat/new" && c.init?.method === "POST")).toBe(true);
  });

  it("links chat messages to the recent store event until the operator dismisses it", async () => {
    const { calls } = mockBackend({
      ...baseRoutes(),
      "/learning/status": () =>
        json(learning({ active_event: { event_id: "q-1", event_type: "queue_count_changed", data: { queue_count: 12 }, age_seconds: 30 } })),
      "POST /ask": () => json({ ok: true, answer: "done" }),
    });
    renderApp();
    expect(await screen.findByText(/Responding to:/)).toBeInTheDocument();
    await sendQuestion("switch to express");
    await screen.findByText("done");
    const asks = () => calls.filter((c) => c.url === "/ask").map((c) => JSON.parse(String(c.init?.body)));
    expect(asks()[0]).toEqual({ question: "switch to express", event_id: "q-1" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Not about this event" }));
    expect(screen.queryByText(/Responding to:/)).toBeNull();
    await sendQuestion("thanks");
    await waitFor(() => expect(asks()).toHaveLength(2));
    expect(asks()[1]).toEqual({ question: "thanks" });
  });

  it("sends the operator's rejection reason, and cancelling the prompt keeps the proposal", async () => {
    const { calls } = mockBackend({
      ...baseRoutes(),
      "/autonomy/status": () => json({ ...emptyAutonomy, pending: 1, proposals: [proposal()] }),
      "POST /autonomy/proposals/p1/reject": () => json({ ok: true, proposal: proposal({ status: "rejected" }) }),
    });
    renderApp();
    const user = userEvent.setup();
    vi.mocked(window.prompt).mockReturnValueOnce(null);
    await user.click(await screen.findByRole("button", { name: /Reject: / }));
    expect(calls.some((c) => c.url.endsWith("/reject"))).toBe(false);
    vi.mocked(window.prompt).mockReturnValueOnce("  we go express instead  ");
    await user.click(screen.getByRole("button", { name: /Reject: / }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/reject"))).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/reject"))?.init?.body).toBe(JSON.stringify({ reason: "we go express instead" }));
  });

  it("offers learning at the threshold, then reviews and approves the learned skill", async () => {
    let state = learning({ unlearnt_actions: 24, ready: [{ service: "kiosk", count: 24 }] });
    const pendingSkill = {
      id: "abcd1234",
      skill: "learned-kiosk",
      removed: 0,
      rules: [{ when: "queue_count ≥ 10", then: "mode → express", taught: 14, matched: 14, rejected: 0, new: true }],
    };
    const { calls } = mockBackend({
      ...baseRoutes(),
      "/learning/status": () => json(state),
      "POST /learning/run": () => {
        state = learning({ unlearnt_actions: 24, pending_skill_writes: 1, pending: [pendingSkill] });
        return json({ ok: true });
      },
      "POST /learning/pending/abcd1234/approve": () => {
        state = learning();
        return json({ ok: true });
      },
    });
    renderApp();
    expect(await screen.findByText("Hermes can learn from 24 kiosk operator actions")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Learn now" }));
    expect(JSON.parse(String(calls.find((c) => c.url === "/learning/run")?.init?.body))).toEqual({ service: "kiosk" });
    expect(await screen.findByText("When queue_count ≥ 10")).toBeInTheDocument();
    expect(screen.getByText("taught 14× of 14")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve skill" }));
    expect(await screen.findByText("learned-kiosk is approved and active from the next event.")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/learning/pending/abcd1234/approve")).toBe(true);
  });
});
