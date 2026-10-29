# How It Works

![QSR Store Agent architecture](_assets/architecture.svg)

## Components

| Component | Role |
|---|---|
| Operator UI | Web interface for chat, connected-service status, decisions, approvals, and learning. Also receives events from store systems. |
| Agent runtime (Hermes) | Understands the request, picks the relevant store skills, calls store services, and composes the answer. Keeps operator preferences in memory. |
| OpenVINO™ Model Server | Serves the Qwen3 INT4 language model set by `MODEL_ID` on the Intel® GPU through an OpenAI-compatible API. |
| Skills | Short procedures, one per store domain, that tell the agent which service and fields answer which question. |
| Learner | Turns recorded operator actions into a learned skill per service. Each rule is checked against the records, and an operator approves the skill. |
| Store services (MCP) | Own the store data and actions, and send the store events, for example kiosk queue changes or weather changes. Each service validates its own actions and enforces its own policy. Services run on their own hosts or share one; the agent and its model run on a separate machine. |

The agent never holds store data itself. It reads data from the services at
the moment of the question, so answers reflect the current state of the store.

## Answering a Question

1. The operator asks a question in the UI.
2. A scope check declines questions that are unrelated to the store.
3. The agent loads the matching skill, for example `kiosk-operations` for a
   queue question.
4. The language model chooses which service tools to call.
5. The services return live data.
6. The model writes the answer using only the returned data. If a service is
   unavailable, the answer says so instead of guessing.

## Responding to an Event

```text
Store event -> queue -> agent gathers context -> no action  (reason shown)
                                              -> proposal   -> operator approves -> service applies it
                                                                                 -> operator rejects
```

1. A store system posts an event, such as `weather_changed`,
   `queue_count_changed`, or `order_mismatch_detected`.
2. The event is saved and queued. Events are processed one at a time in arrival
   order, and they survive restarts. Duplicate event IDs are ignored.
3. The agent selects relevant skills and reads live context from the services,
   such as queue, staffing, menu, and weather.
4. The agent either explains why no action is needed, or proposes a specific
   action, such as hiding a slow-to-prepare menu item while the queue is long.
5. The proposal appears in **Autonomy Decisions**. It expires after five
   minutes if nobody acts on it.
6. On approval, the owning service validates and applies the action.

There is no fixed rule such as "rain means add hot drinks". The agent decides
from the current context, and the operator stays in control.

## Learning From Operators

When an event is shown, the operator can approve or reject the proposal, give a
reason, or tell the agent in chat what to do instead. These responses are
recorded. After enough responses for a service, the operator can start
learning. The agent drafts new guidance for that kind of event, the guidance is
checked against the recorded history, and the operator reviews it before it
takes effect. Approved guidance is used for future events from that service.

## Stored Data

All state is kept in Docker volumes on the edge system:

| Volume | Contents |
|---|---|
| `autonomy-state` | Event queue, decisions, and approvals |
| `learning` | Operator response history, learned guidance, and agent memory |
| `weather-state` | Current simulated weather |

`make down` keeps the volumes. To remove all data as well, run
`docker compose down -v`.

## Trust and Safety

- **Local inference:** prompts and store data are processed on the edge system
  and are not sent to a cloud model.
- **Approval required:** event-driven actions run only after an operator
  approves them.
- **Service-owned policy:** each store service validates its own actions,
  independently of the agent.
- **Grounded answers:** the agent is instructed to answer only from service
  data and to report missing coverage.
- **Scope limits:** off-topic questions are declined before a full model turn.
