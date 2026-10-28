// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { useId } from "react";
import { RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { ServicesState } from "@/hooks/use-services";

type Props = Pick<ServicesState, "phase" | "servers" | "statuses" | "error"> & { onRefresh: () => void };

function ServiceRow({ name, status }: { name: string; status: { ok: boolean; tools: number } | undefined }) {
  const tone = status === undefined ? "status-neutral" : status.ok ? "status-success" : "status-error";
  const label = status === undefined ? "Status not known" : status.ok ? "Online" : "Offline";
  const meta = status === undefined ? "" : status.ok ? `${status.tools} tools` : "offline";
  return (
    <li className="flex items-center gap-3 rounded-lg border px-3 py-2">
      <span aria-hidden className={`${tone} size-2.5 shrink-0 rounded-full bg-(--status-color)`} />
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{name}</span>
      {meta ? (
        <Badge variant="outline" className={`${tone} border-(--status-border) bg-(--status-bg) text-(--status-fg)`}>
          <span className="sr-only">{`${name}: ${label}. `}</span>
          {meta}
        </Badge>
      ) : (
        <span className="sr-only">{`${name}: ${label}`}</span>
      )}
    </li>
  );
}

export function ServicesPanel({ phase, servers, statuses, error, onRefresh }: Props) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 id={titleId} className="text-sm font-semibold">Connected apps</h2>
        <span aria-label="Connected apps count" className="text-xs text-muted-foreground">
          {phase === "loading" ? "…" : phase === "error" ? "!" : servers.length}
        </span>
        <Button variant="outline" size="sm" onClick={onRefresh} aria-label="Refresh services, status and autonomy">
          <RefreshCw aria-hidden /> Refresh
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
        {phase === "loading" && servers.length === 0 ? (
          <div role="status" aria-label="Loading services" className="space-y-2">
            <Skeleton className="h-11 w-full" />
            <Skeleton className="h-11 w-full" />
            <Skeleton className="h-11 w-full" />
          </div>
        ) : phase === "error" ? (
          <p role="alert" className="status-error rounded-lg border border-(--status-border) bg-(--status-bg) p-3 text-sm text-(--status-fg)">
            {error ?? "Status unavailable"}
          </p>
        ) : servers.length === 0 ? (
          <p className="text-sm text-muted-foreground">No services connected</p>
        ) : (
          <ul className="space-y-2">
            {servers.map((name) => (
              <ServiceRow key={name} name={name} status={statuses?.[name]} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
