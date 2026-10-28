// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { Button } from "@/components/ui/button";
import { SUGGESTIONS } from "@/lib/chat-suggestions";

const MAX_LABEL = 46;
const shorten = (text: string) => (text.length > MAX_LABEL ? `${text.slice(0, MAX_LABEL - 2)}…` : text);

export function SuggestionChips({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2 px-4 pb-2" aria-label="Suggested questions" role="group">
      {SUGGESTIONS.map((text) => (
        <Button key={text} variant="outline" size="sm" className="rounded-full" title={text} aria-label={text} onClick={() => onPick(text)}>
          {shorten(text)}
        </Button>
      ))}
    </div>
  );
}
