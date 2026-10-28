// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/hooks/use-chat";

// Message text is rendered as a plain React text child: never as HTML.
export function MessageBubble({ message }: { message: ChatMessage }) {
  const user = message.role === "user";
  return (
    <div className={cn("flex", user ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-4 py-2 text-sm leading-relaxed",
          user && "bg-primary text-primary-foreground",
          !user && message.state !== "error" && "border bg-card",
          message.state === "error" && "status-error border border-(--status-border) bg-(--status-bg) text-(--status-fg)",
        )}
        data-role={message.role}
        data-state={message.state}
      >
        <span className="sr-only">{user ? "You: " : "Agent: "}</span>
        {message.text || (message.state === "pending" ? <span className="animate-pulse text-muted-foreground">Thinking…</span> : null)}
      </div>
    </div>
  );
}
