// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from "react";
import { decideSkill, fetchLearningStatus, startLearning } from "@/api/client";
import type { LearningStatus, PendingSkill } from "@/api/types";
import { useInterval } from "./use-interval";

export const LEARNING_POLL_MS = 5_000;

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

/**
 * Learning journal state from `/learning/status`: the store event chat messages are linked to,
 * the "Hermes can learn" card, and review of staged learned skills. A newly staged skill opens the
 * review once; every learned skill still needs the operator's approval.
 */
export function useLearning(onError?: (text: string) => void) {
  const [status, setStatus] = useState<LearningStatus | null>(null);
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [working, setWorking] = useState(false);
  const reviewed = useRef(new Set<string>());
  const mounted = useRef(true);

  const load = useCallback(async () => {
    try {
      const next = await fetchLearningStatus();
      if (!mounted.current) return;
      setStatus(next);
      const pending = next.pending[0];
      if (pending && !reviewed.current.has(pending.id)) {
        reviewed.current.add(pending.id);
        setNote("");
        setOpen(true);
      }
    } catch {
      if (mounted.current) setStatus(null);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  useInterval(() => void load(), LEARNING_POLL_MS);

  const learn = useCallback(
    async (service: string) => {
      setWorking(true);
      try {
        await startLearning(service);
        setNote("");
        setOpen(true);
      } catch (error) {
        onError?.(`Learning failed to start: ${message(error)}`);
      } finally {
        if (mounted.current) setWorking(false);
        void load();
      }
    },
    [load, onError],
  );

  const decide = useCallback(
    async (pending: PendingSkill, decision: "approve" | "reject") => {
      setWorking(true);
      try {
        await decideSkill(pending.id, decision);
        setNote(
          decision === "approve"
            ? `${pending.skill} is approved and active from the next event.`
            : "Skill change rejected. The operator actions stay available for the next learning run.",
        );
      } catch (error) {
        setNote(`Could not ${decision} the skill: ${message(error)}`);
      } finally {
        if (mounted.current) setWorking(false);
        void load();
      }
    },
    [load],
  );

  const active = status?.active_event ?? null;
  const linkedEvent = active && !dismissed.has(active.event_id) ? active : null;

  return {
    status,
    linkedEvent,
    dismissEvent: () => active && setDismissed((previous) => new Set(previous).add(active.event_id)),
    dialog: { open, note, working },
    openDialog: () => {
      setNote("");
      setOpen(true);
    },
    closeDialog: () => setOpen(false),
    learn,
    decide,
    refresh: load,
  };
}
