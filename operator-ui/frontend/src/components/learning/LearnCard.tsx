// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { GraduationCap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { LearningStatus } from "@/api/types";

interface Props {
  status: LearningStatus;
  working: boolean;
  onLearn: (service: string) => void;
  onOpen: () => void;
}

/** Learning summary and the "Hermes can learn" / review card at the top of the autonomy panel. */
export function LearnCard({ status, working, onLearn, onOpen }: Props) {
  const pending = status.pending[0];
  const ready = status.ready[0];
  const { learner } = status;
  let title = "";
  let detail = "";
  let action: "Review" | "View" | "Learn now" | null = null;
  if (pending) {
    title = "New skill ready for review";
    detail = `${pending.skill} · ${pending.rules.length} rules learnt from operator actions`;
    action = "Review";
  } else if (learner.running) {
    title = `Hermes is learning ${learner.service ?? ""} rules…`;
    detail = learner.log.at(-1) ?? "Analysing operator actions";
    action = "View";
  } else if (ready) {
    title = `Hermes can learn from ${ready.count} ${ready.service} operator actions`;
    detail = learner.error
      ? `Last run: ${learner.error}`
      : `Threshold ${status.threshold} reached · learning takes about a minute`;
    action = "Learn now";
  }
  const summary = [`Learning: ${status.unlearnt_actions} operator actions to learn from`];
  if (status.pending_skill_writes) summary.push(`${status.pending_skill_writes} skill change awaiting approval`);
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground" data-testid="learning-state">{summary.join(" · ")}</p>
      {action ? (
        <Card size="sm" data-testid="learn-card" className="border-primary/40">
          <CardContent className="flex items-start gap-3">
            <GraduationCap aria-hidden className="mt-0.5 size-4 shrink-0 text-primary" />
            <div className="min-w-0 flex-1 space-y-1">
              <p className="text-sm font-semibold break-words">{title}</p>
              <p className="text-xs break-words text-muted-foreground">{detail}</p>
            </div>
            <Button
              size="sm"
              disabled={working}
              onClick={() => (action === "Learn now" && ready ? onLearn(ready.service) : onOpen())}
            >
              {action}
            </Button>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
