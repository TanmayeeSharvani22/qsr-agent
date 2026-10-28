---
name: qsr-agent-ui
description: Build or change the QSR Agent operator UI (operator-ui/frontend) — React, TypeScript, Tailwind CSS v4 and shadcn/ui — following the project's design tokens, backend API contracts, chat (`/ask`), autonomy approval, accessibility and security rules. Use for any UI work in operator-ui/.
license: Apache-2.0
compatibility: Node.js >= 20.19, npm 10+, Python backend in operator-ui/app.py
metadata:
  derived-from: open-edge-platform/edge-ai-libraries PR 3449 (draft) unified-ui-ux-builder, commit f2e347b
allowed-tools: shell
---

# QSR Agent UI

Use this skill for every change to `operator-ui/frontend/`. It adapts the draft
"unified-ui-ux-builder" guidance (Stack A: React + Tailwind + shadcn) to this
project. The Python backend is the source of truth: **never** copy business
logic into React and **never** change backend behaviour just to suit a component.

## Stack and structure

React 19, TypeScript, Tailwind CSS v4, shadcn/ui (Base UI, `base-nova`), Vite 7,
Vitest 3 + Testing Library, lucide-react icons, sonner toasts. Layout and commands
are in `docs/operator-ui.md`. Deviations from the reference skill (keep them):

- **No Redux.** State is small: hooks in `src/hooks/` (`use-services`, `use-chat`,
  `use-autonomy`, `use-theme`). Approved by the team.
- **Vite 7 / Vitest 3**, not newer: npm 10.8 on Node 20 cannot resolve Vite 8 / Vitest 4+.
- Dark `--destructive` stays coral and `--muted-foreground` is darker (contrast AA).

## Workflow for a change

1. Read `references/api-contracts.md` and the component you will touch.
2. New screen/layout or changed structure: update the draw.io wireframe in
   `operator-ui/wireframes/` and get user approval **before** building. Small
   fixes inside existing panels do not need one.
3. Reuse `src/components/ui/*` (add shadcn pieces with `npx shadcn@latest add <name>`, run via npx; it is not a project dependency);
   keep display wording in `src/lib/format.ts`; keep HTTP in `src/api/` only.
4. Use design tokens (`references/design-and-a11y.md`); no hard-coded colours.
5. Add tests next to the code. Then run, in `operator-ui/frontend`:
   `npm run typecheck && npm run lint && npm test && npm run build`
   and `python -m unittest discover -s tests/operator_ui -p "test_*.py"` if
   `app.py` serving changed.
6. Every new source file starts with the SPDX header
   (`SPDX-FileCopyrightText: (C) 2026 Intel Corporation`, `Apache-2.0`).

## Hard rules

- **Safe rendering:** backend, model and event content is untrusted. Render it
  only as React text children. `dangerouslySetInnerHTML` is lint-blocked; do not
  build HTML strings or unvalidated `href`/`src` from data.
- **Single API layer:** all `fetch` calls live in `src/api/`; parse and validate
  responses there; map failures to `ApiError`. Keep existing paths and payloads.
- **Chat:** use `POST /ask` `{question}` only, as the original UI did. One request per
  question; no retries, no client-side timeout, no streaming and no answer
  post-processing (the backend normalises answers). Show `Error: <error|unknown>` for
  `{ok:false}` and `Request failed: <exception>` otherwise. `/ask/stream` stays
  unused until a separate, approved enhancement.
- **Services:** show only states the backend reports (checking, online with
  tool count, offline, error, empty). Do not invent "stopped".
- **Autonomy:** the backend owns proposal lifecycle. The UI only calls
  `POST /autonomy/proposals/{id}/approve|reject` with `{}`, disables the buttons
  while in flight and refetches `/autonomy/status` only after success. A failure is
  shown as a chat error bubble `Autonomy action failed: Error: <message>` (toast is
  extra presentation).
  A proposal needing approval must never be auto-approved or hidden. Mark
  simulated actions (`result.placeholder` / placeholder observation source) as Demo.
- **Polling:** services 30 s, autonomy 5 s, plain intervals like the original; Refresh = `/servers`, `/status?force=1`, `/autonomy/status`. No client-side timeouts.
- **No secrets** or env-derived server config in the bundle. No CORS changes.
- **Do not** add a SPA fallback to `app.py`; unknown paths must stay 404.

## Done means

Typecheck, lint, tests and production build pass; every state (loading, empty,
error, success) is handled; keyboard and screen-reader paths work; light and
dark themes both look right at desktop, tablet and phone widths.
