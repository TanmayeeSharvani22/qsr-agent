# Operator UI

[Documentation guide](index.md) | [Setup](setup.md) | [Architecture](architecture.md)

The operator UI is a React single-page app served by the Python backend
(`operator-ui/app.py`). The backend keeps all business logic and API routes;
the frontend only presents them.

## Layout

```text
operator-ui/
  app.py              Python HTTP server: API routes + serves operator-ui/dist
  dist/               Production build output (generated, git-ignored)
  frontend/           React + TypeScript + Tailwind CSS v4 + shadcn/ui (Vite)
    src/api/          Typed fetch client and response parsers
    src/hooks/        State/polling hooks: services, chat, autonomy, learning, theme
    src/components/   layout, services, chat, autonomy, learning, theme, ui (shadcn)
    src/lib/          Display-only formatting and autonomy ordering helpers
  wireframes/         Approved draw.io wireframe
```

Three columns (Services, Chat, Autonomy) on desktop, narrower columns on
tablet, and a stacked layout on phones where Services opens in a drawer.
Light/dark theme is stored in `localStorage["qsr-theme"]`.

Chat keeps one Hermes conversation; **New chat** starts a fresh one (Hermes
memory is kept). While a store event is recent, a banner links the next chat
message to it so the operator's instruction is journaled for learning; rejecting
a proposal asks for an optional reason. The autonomy column shows the learning
summary, a **Learn now** card at the threshold, and a review sheet where the
operator approves or rejects each learned skill (`/learning/*` routes).

## Requirements

- Node.js **>= 20.19** (tested on 20.20) and npm 10+. Node is only needed to
  build; the Python server serves the compiled files.
- Vite 7 and Vitest 3 are pinned because newer majors need Node 22+ or break
  `npm` 10.8 dependency resolution.

## Commands (run in `operator-ui/frontend`)

| Task | Command |
|---|---|
| Install | `npm ci` |
| Dev server (HMR, proxies API to `http://127.0.0.1:8600`) | `npm run dev` |
| Type check | `npm run typecheck` |
| Lint | `npm run lint` |
| Unit/component tests | `npm test` |
| Production build (to `../dist`) | `npm run build` |

Set `VITE_API_BASE` to proxy the dev server to a backend on another address.
Python tests: `python -m unittest discover -s tests/operator_ui -p "test_*.py"`.

## How the backend serves it

- `/` and `/index.html` return `dist/index.html` (`Cache-Control: no-store`).
- `/assets/*` returns hashed files from `dist/assets` only (extension
  allow-list, no path traversal, immutable caching).
- There is **no** SPA fallback: unknown paths stay `404`, so API requests are
  never answered with HTML. The app has a single URL, so refresh works.
- If `dist/` is missing, `/` returns `503` with the build command.

## Chat and behaviour parity

This migration is UI-only: every request, response interpretation and user-visible
message matches the original inline UI. Chat uses `POST /ask` with `{question}` only: one
request per question, no retry, no client-side timeout and no answer post-processing
(the backend already normalises the answer). Failures show `Error: <error|unknown>` for
`{ok:false}` bodies (any HTTP status) and `Request failed: <exception>` otherwise.
Services poll `/status` every 30 s and autonomy every 5 s; Refresh reloads `/servers`,
`/status?force=1` and `/autonomy/status`. A failed approve/reject appears as a chat error
bubble (`Autonomy action failed: Error: <message>`) and does not reload the list.

`POST /ask/stream` is untouched in the backend but not used by the UI. Streaming could be
proposed as a separate future enhancement (it returns raw Hermes output that `/ask`
normalises server-side).

## Running

- **Docker/Compose:** the `Dockerfile` has a Node build stage and copies the
  compiled `dist` into the runtime image. Nothing else changes:
  `docker compose up --build`.
- **Host (`scripts/setup.sh`):** builds the frontend on first run when `npm`
  is available and `dist` is missing. To rebuild after UI edits, run
  `npm run build` and reload; the server reads files per request.

No new environment variables are required for production.

## Extending the UI

Follow `.github/skills/qsr-agent-ui/SKILL.md` (design tokens, API contracts,
chat and approval rules, accessibility and security requirements).
