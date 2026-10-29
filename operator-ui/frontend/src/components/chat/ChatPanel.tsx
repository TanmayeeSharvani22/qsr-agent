// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { MessageSquarePlus } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { ActiveEvent } from "@/api/types";
import type { ChatMessage, ChatStatus } from "@/hooks/use-chat";
import { ChatInput } from "./ChatInput";
import { EventLinkBanner } from "./EventLinkBanner";
import { MessageList } from "./MessageList";
import { SuggestionChips } from "./SuggestionChips";

const STATUS_TEXT = { ready: "ready", thinking: "thinking…" } as const;

interface Props {
  messages: ChatMessage[];
  status: ChatStatus;
  send: (question: string, eventId?: string) => Promise<boolean>;
  onNewChat: () => void;
  linkedEvent?: ActiveEvent | null;
  onDismissEvent?: () => void;
}

export function ChatPanel({ messages, status, send, onNewChat, linkedEvent, onDismissEvent }: Props) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const submit = async () => {
    const question = draft;
    setDraft("");
    const sent = await send(question, linkedEvent?.event_id);
    if (!sent) setDraft(question);
    inputRef.current?.focus();
  };
  return (
    <section aria-labelledby="chat-title" className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
        <h2 id="chat-title" className="text-sm font-semibold">Operator Chat</h2>
        <div className="flex items-center gap-2">
          <span role="status" className="text-xs text-muted-foreground">{STATUS_TEXT[status]}</span>
          <Button
            size="xs"
            variant="outline"
            disabled={status !== "ready"}
            onClick={onNewChat}
            title="Start a fresh conversation; Hermes memory is kept"
          >
            <MessageSquarePlus aria-hidden /> New chat
          </Button>
        </div>
      </div>
      <MessageList messages={messages} />
      <SuggestionChips
        onPick={(text) => {
          setDraft(text);
          inputRef.current?.focus();
        }}
      />
      {linkedEvent && onDismissEvent ? <EventLinkBanner event={linkedEvent} onDismiss={onDismissEvent} /> : null}
      <ChatInput value={draft} onChange={setDraft} onSubmit={() => void submit()} busy={status !== "ready"} inputRef={inputRef} />
    </section>
  );
}
