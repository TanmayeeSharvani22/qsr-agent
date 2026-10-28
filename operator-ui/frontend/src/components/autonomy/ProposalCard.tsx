// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Proposal } from "@/api/types";
import { actionTitle, isDemoProposal, proposalResultNote, proposalContext } from "@/lib/format";
import { StatusBadge } from "./StatusBadge";

interface Props {
  proposal: Proposal;
  busy: boolean;
  onDecide: (id: string, decision: "approve" | "reject") => void;
}

export function ProposalCard({ proposal, busy, onDecide }: Props) {
  const title = actionTitle(proposal);
  return (
    <Card size="sm" data-testid="proposal" data-status={proposal.status}>
      <CardContent className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-semibold break-words">{title}</h3>
          <StatusBadge status={proposal.status} />
        </div>
        <p className="text-xs text-muted-foreground">{proposalContext(proposal)}</p>
        {proposal.status === "pending" ? (
          <p className="text-sm break-words">Hermes: {proposal.summary || "Action proposed for review."}</p>
        ) : (
          <>
            {isDemoProposal(proposal) ? <p className="text-xs text-muted-foreground">Demo · simulated action</p> : null}
            {proposal.result ? <p className="text-sm break-words">{proposalResultNote(proposal)}</p> : null}
          </>
        )}
        {proposal.status === "pending" ? (
          <>
            <details className="text-xs">
              <summary className="cursor-pointer text-muted-foreground">Technical details</summary>
              <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-muted p-2 whitespace-pre-wrap break-all">
                {proposal.tool}
                {"\n"}
                {JSON.stringify(proposal.arguments, null, 2)}
              </pre>
            </details>
            <div className="flex gap-2">
              <Button size="sm" disabled={busy} onClick={() => onDecide(proposal.id, "approve")} aria-label={`Approve: ${title}`}>
                <Check aria-hidden /> Approve
              </Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => onDecide(proposal.id, "reject")} aria-label={`Reject: ${title}`}>
                <X aria-hidden /> Reject
              </Button>
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
