// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ApiError, decideProposal, fetchAutonomyStatus } from "@/api/client";
import type { AutonomyStatus } from "@/api/types";
import { actionTitle } from "@/lib/format";
import { useInterval } from "./use-interval";

export const AUTONOMY_POLL_MS = 5_000;

export type AutonomyPhase = "loading" | "ready" | "error";

const UNAVAILABLE = "Autonomy unavailable";
// The original UI printed `String(Error)` for failed decisions, i.e. "Error: <message>".
const describe = (error: unknown) => (error instanceof ApiError ? `Error: ${error.message}` : String(error));

/** `onActionError` receives the failure text so the app can show it in the chat, as the original UI did. */
export function useAutonomy(onActionError?: (text: string) => void) {
  const [data, setData] = useState<AutonomyStatus | null>(null);
  const [fetchedAt, setFetchedAt] = useState(0);
  const [phase, setPhase] = useState<AutonomyPhase>("loading");
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const mounted = useRef(true);

  // Responses are applied as they arrive; a failure clears the list, like the original UI.
  const load = useCallback(async () => {
    try {
      const next = await fetchAutonomyStatus();
      if (!mounted.current) return;
      setData(next);
      setFetchedAt(Date.now());
      setPhase("ready");
    } catch {
      if (!mounted.current) return;
      setData(null);
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    // Initial fetch on mount; state is only set when the request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  useInterval(() => void load(), AUTONOMY_POLL_MS);

  const decide = useCallback(
    async (proposalId: string, decision: "approve" | "reject", reason = "") => {
      setBusy((previous) => new Set(previous).add(proposalId));
      try {
        const result = await decideProposal(proposalId, decision, reason);
        const proposal = result.proposal;
        const title = proposal ? actionTitle(proposal) : "Action";
        if (decision === "reject") toast.success(`Rejected: ${title}`);
        else if (proposal?.status === "failed") toast.error(`${title} was not completed. Review the latest event before trying again.`);
        else toast.success(`Approved: ${title}`);
        void load();
      } catch (caught) {
        // Failure leaves the list untouched (no reload), as before.
        const text = `Autonomy action failed: ${describe(caught)}`;
        toast.error(text);
        onActionError?.(text);
      } finally {
        setBusy((previous) => {
          const next = new Set(previous);
          next.delete(proposalId);
          return next;
        });
      }
    },
    [load, onActionError],
  );

  return { data, fetchedAt, phase, error: phase === "error" ? UNAVAILABLE : null, busy, refresh: load, decide };
}
