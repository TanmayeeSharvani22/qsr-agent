# Operator Guide

Open the operator UI at `http://<host>:8600`. The screen has four areas:

| Area | Use it to |
|---|---|
| **Connected apps** | See which store services the agent can reach and how many tools each one offers |
| **Operator Chat** | Ask questions and give instructions |
| **Autonomy Decisions** | Review events, read the agent's reasoning, and approve or reject proposals |
| **Hermes skill learning** | Appears when the agent has enough operator responses to learn from |

## Ask Questions

Type a question and select **Send**. Answers stream in as they are generated.

Examples:

- *How long is the kiosk queue and what is the wait time?*
- *Which menu items are unavailable right now?*
- *What is the order accuracy rate for the last 30 minutes?*
- *Were there any kitchen safety events this shift?*
- *Which tables need cleaning?*

What the agent can answer depends on which services are connected. Questions
unrelated to the store are declined with: *"I can only help with questions
about this store's connected services."*

The agent remembers the conversation and your stated preferences. Select
**New chat** to start a fresh conversation. Preferences remembered by the
agent carry over. After 30 minutes of inactivity, the next question
automatically starts a new conversation.

## Review Event Decisions

When a store event arrives, it appears in **Autonomy Decisions** with one of
these states:

| State | Meaning |
|---|---|
| Queued / Processing | The agent is evaluating the event |
| Pending | The agent proposes an action and is waiting for you |
| No action | The agent decided no change is needed and explains why |
| Failed | The evaluation did not complete; the event can be sent again |

For a pending proposal, read the reason and select **Approve** to apply it or
**Reject** to discard it. You can add a reason when rejecting, which helps the
agent learn. Proposals expire after five minutes.

While an event is shown, questions you ask in chat are linked to it. For
example, *"Why did you suggest that?"* or *"Switch the kiosks to express mode
instead."* Select **✕** on the event banner if your question is not about that
event.

## Try Demo Events

Change the simulated weather. Valid conditions are `clear`, `cloudy`, `fog`,
`drizzle`, `rain`, `storm`, and `snow`:

```bash
make weather CONDITION=rain TEMP=12
make weather CONDITION=clear NO_EVENT=1    # change silently, no event
```

Queue events come from the kiosk itself: kiosk-core sends one whenever the
count from its queue camera changes. Order-accuracy events come from the
take-away and dine-in services when an order fails validation. See
[Run Kiosk and Order Accuracy on Remote Hosts](get-started/configuration.md#run-kiosk-and-order-accuracy-on-remote-hosts)
for a test event you can send from each host.

Any store system can send its own events. See the
[API Reference](api-reference.md#post-autonomyevents).

## Teach the Agent

The agent records how you respond to events: approvals, rejections with
reasons, and instructions you give in chat while an event is shown. When a
service has 20 responses (`QSR_LEARN_THRESHOLD`), with at least 5 for one event
type (`QSR_LEARN_MIN_EVENT_RECORDS`), the learning card shows **Learn now**.
The command line needs only the 5 per event type (`--min-records`).

1. Select **Learn now**. Learning takes about a minute.
2. When the card shows **New skill ready for review**, select **Review**.
3. Read the learned rules, then approve or reject them.

Approved rules guide the agent's proposals for future events from that service.
Every proposal still needs your approval.

The same steps are available from the command line:

```bash
make learn ARGS=status
make learn ARGS=run
make learn ARGS=pending
make learn ARGS="approve <id>"
```

### Try learning with sample data

To see learning work before you have collected real responses, import the
synthetic sample history for kiosk, weather and order accuracy
(`learning/simulated/event_op_response.jsonl`, 520 records marked
`source: "simulated"`). Use a test deployment only: imported records are added
to the same journal as real operator responses, so do not import them into a
production store.

The sample records use the same menu item IDs, event fields and context as the
smart-kiosk-assistant and Order Accuracy (take-away, dine-in) services, so the
learned rules work with those services:

| Service | Learned behaviour |
|---|---|
| Weather | Rain: Cold Coffee (`DRINK-004`) and Fresh Lime Soda (`DRINK-005`) off. Rain stops: both back on. 29 °C or more: Vanilla Soft Serve (`DESSERT-002`) on |
| Order accuracy | Take-away order with missing items: remake it. Dine-in orders are not remade |
| Kiosk | Long queue: express mode, a fourth kiosk and no upsell. Queue cleared: back to standard |

```bash
docker compose cp learning/simulated/event_op_response.jsonl qsr-agent:/tmp/event_op_response.jsonl
make learn ARGS="import /tmp/event_op_response.jsonl"
make learn ARGS=status
make learn ARGS="run --service kiosk"
make learn ARGS=pending
make learn ARGS="approve <id>"
```

Importing is safe to repeat: records already in the journal are skipped. After
approval, `learned-<service>/SKILL.md` appears under `learning/skills/` in the
`learning` volume, not in the repository's `learning/` folder. Read it with
`docker compose exec qsr-agent cat /opt/qsr/learning/skills/learned-<service>/SKILL.md`.
To discard a proposal, run `make learn ARGS="reject <id>"`.

To learn again from scratch for one service, for example after importing new
sample data, delete its learned skill first (test deployments only):

```bash
docker compose exec qsr-agent rm -rf /opt/qsr/learning/skills/learned-weather
```

The sample file can be regenerated with `python scripts/simulate_service_history.py`.

Notes:

- Learning needs the model server to be running, and takes about a minute.
- Outside Docker, run `scripts/learn.py` with `QSR_MCP_PYTHON` pointing to a
  Python that has `fastmcp` installed (the default is `.venv/mcp/bin/python`).
  Without it the learner cannot read tool schemas and drops its rules.
- Outside Docker, run `python scripts/learn.py setup` once so the learner
  profile reads and writes the `learning/skills` folder you intend to use.
  Use `QSR_LEARNING_DIR` and `QSR_LEARNER_HERMES_HOME` to keep a test run
  separate from real state.

## Command-Line Chat

To chat with the agent in a terminal instead of the browser:

```bash
docker compose exec qsr-agent hermes
```
