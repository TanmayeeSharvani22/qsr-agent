// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { Send } from "lucide-react";
import { useId, type FormEvent, type RefObject } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  busy: boolean;
  inputRef?: RefObject<HTMLInputElement | null>;
}

export function ChatInput({ value, onChange, onSubmit, busy, inputRef }: Props) {
  const id = useId();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <form onSubmit={submit} className="flex gap-2 border-t p-3">
      <label htmlFor={id} className="sr-only">Ask the store agent</label>
      <Input
        id={id}
        ref={inputRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Ask the store agent…"
        autoComplete="off"
      />
      <Button type="submit" disabled={busy || !value.trim()}>
        <Send aria-hidden /> Send
      </Button>
    </form>
  );
}
