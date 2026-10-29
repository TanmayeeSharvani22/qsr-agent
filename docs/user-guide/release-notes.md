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

### Known Limitations

- The bundled kiosk, order-accuracy, and weather data are simulated.
- The operator UI has no built-in authentication. Restrict network access in
  production.
- Self-signed certificates on remote services are trusted on first use at
  start-up. Use properly signed certificates in production.
- One operator conversation and one event are processed at a time.
