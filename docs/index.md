# QSR Store Agent

[Repository overview](../README.md) | **Documentation guide** |
[Setup](setup.md) | [Architecture](architecture.md) |
[Add a service](adding-a-service.md)

This project is a reusable edge-agent pattern for quick-service restaurants.
Hermes handles conversation and orchestration, Qwen3-8B runs locally through
OpenVINO Model Server (OVMS) on an Intel GPU, and independent MCP services own
restaurant data, actions, policy, and audit evidence.

```text
Operator -> Hermes -> OVMS/Qwen -> MCP service -> domain system
         <- answer  <- tool use  <- typed result <- policy/audit
```

The repository includes:

- `mcp-service-sdk` as a Git package dependency: framework-neutral service, policy, log, and MCP binding.
- `tests/mcp-services/`: runnable Kiosk and Order Accuracy simulations.
- `qsr-skills/`: Hermes procedures for domain Q&A and actions.
- `agent-config/hermes/`: reusable local and remote configuration fragments.
- `scripts/setup.sh`: repeatable Linux setup and verification.

The included domain values and actions are simulations. They prove contracts,
routing, action gates, Docker transport, and agent integration; they are not
production restaurant integrations.

## Reading Order

1. Follow [Complete setup](setup.md) to install and run the exact local stack.
2. Read [Architecture](architecture.md) for ownership and trust boundaries.
3. Follow [Adding a service](adding-a-service.md) to integrate another QSR
   domain or replace a simulation with an authoritative service.

After prerequisites are installed, the normal path is:

```bash
git clone https://github.com/unarayan/qsr-agentic-svc.git
cd qsr-agentic-svc
./scripts/setup.sh
hermes
```

Verify an existing installation at any time without changing it:

```bash
./scripts/setup.sh --check
```

## Common Tasks

| Task | Reference |
|---|---|
| Install Hermes and local inference | [Complete setup](setup.md#2-run-setup) |
| Start or inspect OVMS | [Exact OVMS bring-up](setup.md#4-exact-ovms-bring-up) |
| Validate MCP and agent Q&A | [Run and verify](setup.md#5-run-and-verify) |
| Understand component ownership | [Responsibility boundaries](architecture.md#responsibility-boundaries) |
| Deploy remote MCP services | [Remote deployment](architecture.md#remote-deployment) |
| Add a QSR domain | [Adding a QSR service](adding-a-service.md) |

---

[Repository overview](../README.md) | [Next: Complete setup](setup.md)
