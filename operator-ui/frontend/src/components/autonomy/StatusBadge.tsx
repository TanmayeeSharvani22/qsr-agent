// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { Badge } from "@/components/ui/badge";
import { statusLabel } from "@/lib/format";

const TONES: Record<string, string> = {
  pending: "status-info",
  processing: "status-info",
  queued: "status-neutral",
  executing: "status-info",
  executed: "status-success",
  no_action: "status-neutral",
  rejected: "status-neutral",
  superseded: "status-neutral",
  failed: "status-error",
};

export function StatusBadge({ status }: { status: string }) {
  const tone = TONES[status] ?? "status-neutral";
  return (
    <Badge variant="outline" className={`${tone} h-auto whitespace-normal border-(--status-border) bg-(--status-bg) text-(--status-fg)`}>
      {statusLabel(status)}
    </Badge>
  );
}
