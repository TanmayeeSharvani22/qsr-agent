// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { useMemo, type ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import type { AutonomyStatus } from "@/api/types";
import type { AutonomyPhase } from "@/hooks/use-autonomy";
import { autonomySummary, buildAutonomyItems } from "@/lib/autonomy";
import { DecisionCard } from "./DecisionCard";
import { ProposalCard } from "./ProposalCard";

interface Props {
  data: AutonomyStatus | null;
  phase: AutonomyPhase;
  error: string | null;
  /** Time the snapshot was received; elapsed assessment time is measured against it. */
  fetchedAt: number;
  busy: ReadonlySet<string>;
  onDecide: (id: string, decision: "approve" | "reject") => void;
  /** Learning summary and card, shown above the decisions. */
  learning?: ReactNode;
}

export function AutonomyPanel({ data, phase, error, fetchedAt, busy, onDecide, learning }: Props) {
  const items = useMemo(() => (data ? buildAutonomyItems(data) : []), [data]);
  const summary = data ? autonomySummary(data) : phase === "error" ? "Autonomy unavailable" : "Loading…";
  return (
    <section aria-labelledby="autonomy-title" className="flex h-full min-h-0 flex-col">
      <div className="border-b px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 id="autonomy-title" className="text-sm font-semibold">Autonomy Decisions</h2>
          <span aria-label="Awaiting approval" className="text-xs font-medium text-primary">
            {data ? data.pending : phase === "error" ? "!" : "…"}
          </span>
        </div>
        <p role="status" className="text-xs text-muted-foreground">{summary}</p>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {learning}
        {phase === "error" ? (
          <p role="alert" className="status-error rounded-lg border border-(--status-border) bg-(--status-bg) p-3 text-sm text-(--status-fg)">
            {error ?? "Autonomy unavailable"}
          </p>
        ) : null}
        {phase === "loading" ? (
          <div role="status" aria-label="Loading autonomy" className="space-y-2">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : data && data.proposals.length === 0 && data.decisions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No decisions yet</p>
        ) : (
          items.map((item) =>
            item.kind === "proposal" ? (
              <ProposalCard key={item.key} proposal={item.proposal} busy={busy.has(item.proposal.id)} onDecide={onDecide} />
            ) : (
              <DecisionCard key={item.key} decision={item.decision} now={fetchedAt} />
            ),
          )
        )}
      </div>
    </section>
  );
}
