// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme/ThemeToggle";

export function AppHeader({ servicesTrigger }: { servicesTrigger?: ReactNode }) {
  return (
    <header className="flex items-center gap-3 border-b bg-card px-4 py-3">
      <span className="text-lg font-bold tracking-tight text-primary">Intel</span>
      <span className="h-5 w-px bg-border" aria-hidden />
      <div className="min-w-0">
        <h1 className="truncate text-base font-semibold">QSR Store Agent</h1>
        <p className="truncate text-xs text-muted-foreground">Hermes · Qwen3 · MCP</p>
      </div>
      <div className="ml-auto flex items-center gap-2">
        {servicesTrigger}
        <ThemeToggle />
      </div>
    </header>
  );
}
