# Release Notes

## Current Release

### New

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
- Kiosk and order accuracy come from the remote smart-kiosk-assistant and
  Order Accuracy (take-away, dine-in) services; their events drive decisions
  and learning. The built-in kiosk and order-accuracy simulations and
  `make queue` are removed.
- Learning from live events of remote services: list sizes (`.count`), menu
  items by ID, and extra rules fitted from the records for patterns the model
  misses.

### Fixed

- `make learn ARGS=run` on a fresh install creates the learner profile itself.
- The sample learning history uses the real kiosk menu IDs and Order Accuracy
  event fields, so its rules work with the remote services.
- A learned skill can read its own service and every context its rules check.
- A service snapshot that is already stale when read now fails with a clock-skew
  message instead of five retries.
- When the model proposes an action without reading the context it requires
  (for example a menu change without the kiosk snapshot), the agent reads it
  and asks the model to reassess, instead of failing after five rounds.
- The kiosk skill uses the real kiosk tools (`change_menu_items`,
  `update_menu_item`, queue history, order stats, board state, menu requests)
  and fields.

### Known Limitations

- Weather data is simulated unless live Open-Meteo weather is configured.
- The operator UI has no built-in authentication. Restrict network access in
  production.
- Self-signed certificates on remote services are trusted on first use at
  start-up. Use properly signed certificates in production.
- One operator conversation and one event are processed at a time.
- A learned skill lists when to act but cannot forbid an action, so the base
  skill may still propose one operators usually reject.
