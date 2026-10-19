---
name: digital-signage
description: "Trigger, select, and inspect in-store digital signage advertisements via the Digital Signage MCP service (product-detection-driven and agent-commanded ads)."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Digital-Signage, Advertising, Retail-Media]
---

# Digital Signage

Use the `digital-signage` MCP service as the only source of live signage state
and as the only way to change what is displayed. Never answer from memory or
an earlier turn when a fresh tool call is available.

Any request to show, trigger, select, or clear an ad — including video ads
described in free text — REQUIRES an actual `digital-signage` tool call before
you respond. Never compose a response describing what a tool call "will do"
or "is now doing" without having actually invoked it in this turn: a real
response from `trigger_ad`/`trigger_video_ad`/`select_dynamic_ad` always
quotes the exact item name the service resolved and, for video, always
includes the phrase "this can take a few minutes" verbatim. If your draft
reply doesn't contain output copied directly from a tool result, you have not
called the tool yet — call it now instead of sending that reply.

## Video ads specifically take longer — this is expected, not an error

`trigger_video_ad` itself always returns IMMEDIATELY (the video generates in
the background afterward); the tool call does not block or hang. There is no
reason to skip calling it. For "play/show/trigger a video ad" requests:
1. Call `trigger_video_ad` right now, with `item` set to the named product
   (preferred) or `description` set to the user's free text (only if no
   product name was given). Do this before writing any reply text.
2. Your reply must be the tool's returned string, verbatim or near-verbatim
   (it already contains "(this can take a few minutes)" — keep that phrase).
   Do not shorten it, round the duration, or invent your own wording.

## Contract Discovery

Before the first digital-signage tool call in a conversation, call `describe`
to confirm the current read and action tools available. Do not use `describe`
as evidence for live ad state.

## Capability Routing

| User intent or question | Required capability | Fields to use | Answer rule |
|---|---|---|---|
| What's currently showing / current ad / is anything overridden | Retrieve the currently displayed advertisement | product, source (camera-detected vs. agent-commanded), image or video, promo text | State whether the ad is live/camera-driven or an agent override, and which product it's for. |
| What products/items can be advertised | Retrieve the catalog of advertisable products and associations | product names, associated items | Summarize the available products; don't invent products not in the result. |
| Show/display/trigger an ad for a specific product (optionally with custom promo text) | Directly display a specific catalog item's ad | product name, promo text (optional) | Confirm which product was triggered and the promo text used, if any. |
| Play/show a looping video ad for a product | Display a looping video ad | product name, display duration | Confirm which product's video ad was triggered. |
| Pick the best ad given context (weather, demand, time of day, age group) | Resolve a shopping context and select a dynamic ad | weather, demand signal, age_mix, daypart, resolved product | Report which product was selected and why, based only on the returned resolution — don't guess beyond it. |
| Clear/stop/remove the current override ad | Clear any agent-commanded override | — | Confirm the override was cleared; camera-driven ad selection resumes. |
| What the service/tool contract supports | Describe the service's current contract | read tools, action tools | Use only to answer meta-questions about capabilities; never to answer a data question. |

## Complex Questions

For multi-step requests (e.g. "show the right ad for this cold, rainy
evening"), prefer `select_dynamic_ad` over guessing a product yourself — pass
through the context the user gave and let the service resolve it. State
missing evidence instead of inventing a product or promo.
