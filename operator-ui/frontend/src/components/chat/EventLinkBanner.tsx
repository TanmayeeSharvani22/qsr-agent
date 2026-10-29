// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { Link2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ActiveEvent } from "@/api/types";
import { compactEventInfo, eventLabel } from "@/lib/format";

/** Shows which store event the next chat message responds to; the operator's instruction is learnt from. */
export function EventLinkBanner({ event, onDismiss }: { event: ActiveEvent; onDismiss: () => void }) {
  const minutes = Math.floor(event.age_seconds / 60);
  const info = compactEventInfo(event.event_type, event.data, {});
  return (
    <div data-testid="event-link" className="flex items-center gap-2 border-t bg-primary/5 px-4 py-2 text-xs">
      <Link2 aria-hidden className="size-3.5 shrink-0 text-primary" />
      <span className="min-w-0 flex-1 break-words">
        Responding to: {eventLabel(event.event_type)}
        {info ? ` (${info})` : ""}, {minutes < 1 ? "just now" : `${minutes} min ago`}
      </span>
      <Button size="icon-xs" variant="ghost" onClick={onDismiss} aria-label="Not about this event">
        <X aria-hidden />
      </Button>
    </div>
  );
}
