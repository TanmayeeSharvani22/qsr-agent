// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { LearningStatus, PendingSkill } from "@/api/types";

interface Props {
  status: LearningStatus | null;
  open: boolean;
  note: string;
  working: boolean;
  onClose: () => void;
  onDecide: (pending: PendingSkill, decision: "approve" | "reject") => void;
}

/** Review of a learned skill (rules with their evidence) and the learner's progress. */
export function LearnDialog({ status, open, note, working, onClose, onDecide }: Props) {
  const pending = status?.pending[0];
  const learner = status?.learner;
  const showLog = !note && !pending && learner && (learner.running || learner.log.length > 0);
  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent side="right" className="data-[side=right]:sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{pending && !note ? `Review ${pending.skill}` : "Hermes learning"}</SheetTitle>
          <SheetDescription className="sr-only">Learned skills from operator actions</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4" data-testid="learn-body">
          {note ? <p className="text-sm">{note}</p> : null}
          {!note && pending ? (
            <>
              <p className="text-sm text-muted-foreground">
                Hermes wrote {pending.skill} from recorded operator actions. Each rule was checked against those
                records. Approving saves it with Hermes /skills approve; it is used from the next event, and every
                action it proposes still needs your approval.
              </p>
              <ul className="space-y-2">
                {pending.rules.map((rule) => (
                  <li key={`${rule.when}|${rule.then}`} className="learn-rule rounded-lg border p-2 text-sm">
                    <p className="break-words">
                      When {rule.when}
                      {rule.new ? <span className="ml-2 rounded bg-primary/15 px-1 text-xs text-primary">NEW</span> : null}
                    </p>
                    <p className="font-medium break-words">{rule.then}</p>
                    <p className="text-xs text-muted-foreground">
                      taught {rule.taught}× of {rule.matched}
                      {rule.rejected ? ` · rejected ${rule.rejected}×` : ""}
                    </p>
                  </li>
                ))}
              </ul>
              {pending.removed ? (
                <p className="text-sm text-muted-foreground">
                  {pending.removed} earlier rule(s) are no longer supported and will be removed.
                </p>
              ) : null}
            </>
          ) : null}
          {showLog ? (
            <>
              <p className="text-sm">
                {learner.running
                  ? `Hermes is learning ${learner.service ?? ""} rules with the local model. This takes about a minute; event decisions may wait briefly.`
                  : learner.error
                    ? `Learning stopped: ${learner.error}`
                    : "Learning finished."}
              </p>
              <pre className="max-h-72 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">
                {learner.log.join("\n") || "Starting…"}
              </pre>
            </>
          ) : null}
          {!note && !pending && !showLog ? <p className="text-sm text-muted-foreground">Nothing to review right now.</p> : null}
        </div>
        <SheetFooter className="flex-row justify-end gap-2">
          {!note && pending ? (
            <>
              <Button variant="outline" disabled={working} onClick={onClose}>Later</Button>
              <Button variant="destructive" disabled={working} onClick={() => onDecide(pending, "reject")}>Reject</Button>
              <Button disabled={working} onClick={() => onDecide(pending, "approve")}>Approve skill</Button>
            </>
          ) : (
            <Button variant="outline" onClick={onClose}>{learner?.running && !note ? "Hide" : "Close"}</Button>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
