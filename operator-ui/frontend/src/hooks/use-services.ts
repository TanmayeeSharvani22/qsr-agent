// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchServers, fetchStatus } from "@/api/client";
import type { StatusResponse } from "@/api/types";
import { useInterval } from "./use-interval";

export const STATUS_POLL_MS = 30_000;

export type ServicesPhase = "loading" | "ready" | "error";

export interface ServicesState {
  phase: ServicesPhase;
  servers: string[];
  /** Per-service reachability; null until /status has answered (or when it failed). */
  statuses: StatusResponse["services"] | null;
  error: string | null;
}

export function useServices() {
  const [state, setState] = useState<ServicesState>({ phase: "loading", servers: [], statuses: null, error: null });
  const mounted = useRef(true);

  // Like the original UI: a failed /status leaves the indicators as they were, and responses are
  // applied as they arrive (no cancellation of earlier requests).
  const loadStatus = useCallback(async (force = false) => {
    try {
      const data = await fetchStatus(force);
      if (!mounted.current) return;
      setState((previous) => ({ ...previous, statuses: data.ok ? data.services : {} }));
    } catch {
      // leave dots as they were
    }
  }, []);

  const loadServers = useCallback(async () => {
    setState((previous) => ({ ...previous, phase: "loading", error: null }));
    try {
      const data = await fetchServers();
      if (!mounted.current) return;
      // `ok:false` is shown as "no services", exactly as the original did.
      setState({ phase: "ready", servers: data.servers, statuses: null, error: null });
      if (data.servers.length > 0) void loadStatus();
    } catch {
      if (!mounted.current) return;
      setState({ phase: "error", servers: [], statuses: null, error: "Status unavailable" });
    }
  }, [loadStatus]);

  const refresh = useCallback(async () => {
    await Promise.all([loadServers(), loadStatus(true)]);
  }, [loadServers, loadStatus]);

  useEffect(() => {
    mounted.current = true;
    // Initial fetch on mount; state is only set when the request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadServers();
    return () => {
      mounted.current = false;
    };
  }, [loadServers]);

  useInterval(() => void loadStatus(false), STATUS_POLL_MS);

  return { ...state, loadServers, loadStatus, refresh };
}
