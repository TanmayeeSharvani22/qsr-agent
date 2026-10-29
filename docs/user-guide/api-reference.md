# API Reference

The operator UI serves a small HTTP API on port `8600`. All request and
response bodies are JSON unless noted. Request bodies are limited to 64 KiB.

> The API has no built-in authentication. Restrict network access as described
> in [Configuration](get-started/configuration.md#secure-network-access).

## Health

### `GET /health`

Returns `200` while the server is running.

```json
{"status": "ok"}
```

### `GET /ready`

Returns `200` once the model is warmed up and the first answer will be fast,
or `503` while warming up.

```json
{"status": "ready"}
```

## Services

### `GET /servers`

Lists the store services registered with the agent.

### `GET /status`

Returns reachability and tool count for each registered service. Results are
cached briefly. Use `GET /status?force=1` to recheck now.

```json
{"ok": true, "services": {"weather": {"ok": true, "tools": 2}}}
```

## Chat

### `POST /ask/stream`

Asks the agent a question and streams the answer as Server-Sent Events.

| Field | Type | Required | Description |
|---|---|---|---|
| `question` | string | Yes | Up to 4000 characters |
| `event_id` | string | No | Links the question to an event shown in **Autonomy Decisions** |

```bash
curl -N -X POST http://localhost:8600/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"question": "What is the current queue count?"}'
```

Each message is a `data:` line with a JSON object. `delta` messages carry
partial text, and the final `done` message carries the full answer.

### `POST /ask`

Same request as `/ask/stream`. Returns the complete answer in one response:

```json
{"ok": true, "answer": "There are 4 customers in the queue..."}
```

### `POST /chat/new`

Starts a new conversation. The agent's memory of operator preferences is kept.

## Events

### `POST /autonomy/events`

Submits a store event for the agent to evaluate. Returns `202` immediately. The
evaluation runs in the background.

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | string | Yes | Unique ID, up to 200 characters. Resending an ID that was already processed is ignored. Resend a failed ID to retry it |
| `event_type` | string | Yes | Any descriptive name, for example `queue_count_changed` |
| `service` | string | No | Name of the producing service. Needed for the agent to learn from operator responses to this event |
| `store_id` | string | No | Store identifier |
| `occurred_at` | string | No | ISO 8601 timestamp |
| `data` | object | No | Event details |

The whole event must be under 32 KiB.

```bash
curl -X POST http://localhost:8600/autonomy/events \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "queue-0001",
    "event_type": "queue_count_changed",
    "service": "kiosk",
    "store_id": "qsr-001",
    "occurred_at": "2026-10-27T12:00:00Z",
    "data": {"queue_count": 12}
  }'
```

```json
{"ok": true, "event_id": "queue-0001", "duplicate": false, "status": "queued"}
```

### `GET /autonomy/status`

Returns the event queue and recent decisions. Decision states are `queued`,
`processing`, `pending`, `no_action`, and `failed`.

### `POST /autonomy/proposals/{proposal_id}/approve`

### `POST /autonomy/proposals/{proposal_id}/reject`

Approves or rejects a pending proposal. Optional body:

| Field | Type | Description |
|---|---|---|
| `reason` | string | Up to 500 characters. Recorded for learning |

Returns `404` if the proposal does not exist, and `409` if it has expired or
was already decided.

## Learning

### `GET /learning/status`

Returns services with enough operator responses to learn from, learning
progress, and learned rules waiting for review.

### `POST /learning/run`

Starts learning for one service. Body: `{"service": "kiosk"}`. Returns `202`,
or `409` if the service is not ready or learning is already running.

### `POST /learning/pending/{id}/approve`

### `POST /learning/pending/{id}/reject`

Approves or rejects learned rules that are waiting for review.
