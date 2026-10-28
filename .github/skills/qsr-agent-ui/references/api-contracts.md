# Backend API contracts (operator-ui/app.py)

Same-origin, no auth, no CORS. All responses are `Cache-Control: no-store`.
Types live in `src/api/types.ts`; parsers in `src/api/client.ts`.

| Method & path | Purpose | Response |
|---|---|---|
| `GET /` | Compiled UI (`operator-ui/dist/index.html`) | HTML (503 if not built) |
| `GET /assets/*` | Hashed build assets | file |
| `GET /health` / `GET /ready` | Liveness / readiness (503 while warming) | `{status}` |
| `GET /servers` | MCP service names | `{ok, servers[], count, error?}` |
| `GET /status[?force=1]` | Reachability per service (15 s server cache) | `{ok, services:{name:{ok,tools}}}` |
| `GET /autonomy/status` | Queue, decisions, proposals | `{ok, queue, pending, decisions[], proposals[], ...}` |
| `POST /ask` `{question}` | Single answer | `{ok, answer}` or `{ok:false, error}` |
| `POST /ask/stream` `{question}` | SSE; exists in the backend but is **not used** by the UI (future enhancement) | `text/event-stream` |
| `POST /autonomy/proposals/{id}/approve` / `/reject` `{}` | Decide a proposal | `{ok, proposal}`; 404 not found, 409 state conflict |
| `POST /autonomy/events` | Producer webhook (weather etc.) — not used by the UI | 202 |

POST bodies must be JSON objects ≤ 64 KiB. Unknown paths return plain-text 404.

Proposal `status`: pending, executing, executed, rejected, superseded, failed.
Decision `status`: queued, processing, pending, no_action, failed.
Wording for these lives in `src/lib/format.ts`; ordering (attention first, newest
first, ≤10 proposals + ≤5 decisions without a proposal) in `src/lib/autonomy.ts`.
If the contract changes, update `app.py`, types, parsers, tests and this file together.
