# Release Notes: QSR Store Agent

## Version 2026.3.0

**Release Date**: December 2026

**New**:

- Operator chat with live answers from connected store services, using the
  local Qwen3 INT4 model (set by `MODEL_ID`) served by the OpenVINO™ Model Server on an
  Intel® GPU.
- Event-driven recommendations with operator approval for any store event
  type.
- Learning from operator responses, with operator review before learned rules
  take effect.
- Scope guardrail that declines questions unrelated to the store.
- Weather service with on-demand simulation and optional live Open-Meteo data.
- Store skills for kiosk operations, order accuracy, kitchen safety, digital
  signage, café operations, table management, and footfall analytics.
- Single-command deployment with Docker Compose, using a pre-built image or a
  local build.
- Store data comes only from the connected store services; the built-in
  simulations, except weather, are removed.
- Learning from the live events of any connected service.

**Fixed**:

- `make learn ARGS=run` on a fresh install creates the learner profile itself.
- A learned skill can read its own service and every context its rules check.
- A service snapshot that is already stale when read now fails with a clock-skew
  message instead of five retries.
- When the model proposes an action without reading the context it requires,
  the agent reads it and asks the model to reassess, instead of failing after
  five rounds.
- Learned rules waiting for review survive container restarts and rebuilds.
- `make learn` trusts the self-signed certificates of remote services.
- Learning no longer adds a rule from only two records that the other rules
  miss.
- Operator chat loads the matching store skill before it answers or acts.
- Store skills use the current tools and fields of their services, and answer
  time-window and count questions correctly.

**Known Limitations**:

- Weather data is simulated unless live Open-Meteo weather is configured.
- The operator UI has no built-in authentication. Restrict network access in
  production.
- Self-signed certificates on remote services are trusted on first use at
  start-up. Use properly signed certificates in production.
- One operator conversation and one event are processed at a time.
- A learned skill lists when to act but cannot forbid an action, so the base
  skill may still propose one operators usually reject.
