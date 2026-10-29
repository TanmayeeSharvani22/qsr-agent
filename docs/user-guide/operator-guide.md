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

Simulate a queue change:

```bash
make queue COUNT=12 WAIT=9
```

Any store system can send its own events. See the
[API Reference](api-reference.md#post-autonomyevents).

## Teach the Agent

The agent records how you respond to events: approvals, rejections with
reasons, and instructions you give in chat while an event is shown. When enough
responses have been collected for a service, the learning card shows
**Learn now**.

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

## Command-Line Chat

To chat with the agent in a terminal instead of the browser:

```bash
docker compose exec qsr-agent hermes
```
