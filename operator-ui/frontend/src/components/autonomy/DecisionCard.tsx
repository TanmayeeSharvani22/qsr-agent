// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { Card, CardContent } from "@/components/ui/card";
import type { Decision } from "@/api/types";
import { decisionContext, decisionNote, elapsedSeconds, eventLabel } from "@/lib/format";
import { StatusBadge } from "./StatusBadge";

export function DecisionCard({ decision, now }: { decision: Decision; now: number }) {
  const progress = decision.status === "processing" ? decision.progress : undefined;
  return (
    <Card size="sm" data-testid="decision" data-status={decision.status}>
      <CardContent className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold">{eventLabel(decision.event.event_type)}</h3>
          <StatusBadge status={decision.status} />
        </div>
        <p className="text-xs text-muted-foreground">{decisionContext(decision)}</p>
        <p className="text-sm break-words">{decisionNote(decision)}</p>
        {progress ? (
          <p className="text-xs text-muted-foreground">
            Assessing · Step {progress.round} of {progress.max_rounds} · {elapsedSeconds(progress.stage_started_at, now)}s
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
