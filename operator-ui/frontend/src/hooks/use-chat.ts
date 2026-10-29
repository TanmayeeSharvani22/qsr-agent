// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from "react";
import { ask, newChat } from "@/api/client";
import { WELCOME_MESSAGE } from "@/lib/chat-suggestions";

export type ChatRole = "user" | "assistant";
export type MessageState = "pending" | "done" | "error";

export interface ChatMessage {
  id: number;
  role: ChatRole;
  text: string;
  state: MessageState;
}

export type ChatStatus = "ready" | "thinking";

/**
 * Chat uses the single-response `POST /ask` endpoint exactly like the original UI: one request per
 * question, no streaming, no retries, no client-side timeout and no answer post-processing (the
 * backend already normalises the answer).
 */
export function useChat() {
  const nextId = useRef(1);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: 0, role: "assistant", text: WELCOME_MESSAGE, state: "done" },
  ]);
  const [status, setStatus] = useState<ChatStatus>("ready");
  const busy = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const patch = useCallback((id: number, update: Partial<ChatMessage>) => {
    if (!mounted.current) return;
    setMessages((previous) => previous.map((message) => (message.id === id ? { ...message, ...update } : message)));
  }, []);

  /** Append a bot error bubble (used for failed approve/reject actions, as the original UI did). */
  const addError = useCallback((text: string) => {
    const id = nextId.current++;
    setMessages((previous) => [...previous, { id, role: "assistant", text, state: "error" }]);
  }, []);

  const send = useCallback(
    async (rawQuestion: string, eventId?: string) => {
      const question = rawQuestion.trim();
      if (!question || busy.current) return false;
      busy.current = true;
      const replyId = nextId.current + 1;
      setMessages((previous) => [
        ...previous,
        { id: nextId.current, role: "user", text: question, state: "done" },
        { id: replyId, role: "assistant", text: "", state: "pending" },
      ]);
      nextId.current += 2;
      setStatus("thinking");
      try {
        const answer = await ask(question, eventId);
        if (answer.ok) patch(replyId, { text: answer.answer, state: "done" });
        else patch(replyId, { text: `Error: ${answer.error}`, state: "error" });
      } catch (error) {
        patch(replyId, { text: `Request failed: ${String(error)}`, state: "error" });
      } finally {
        busy.current = false;
        if (mounted.current) setStatus("ready");
      }
      return true;
    },
    [patch],
  );

  /** Start a fresh Hermes conversation and clear the transcript; Hermes memory is kept. */
  const reset = useCallback(async () => {
    if (busy.current) return;
    try {
      await newChat();
      if (mounted.current) setMessages([{ id: nextId.current++, role: "assistant", text: WELCOME_MESSAGE, state: "done" }]);
    } catch (error) {
      addError(`Could not start a new chat: ${error instanceof Error ? error.message : String(error)}`);
    }
  }, [addError]);

  return { messages, status, send, addError, reset };
}
