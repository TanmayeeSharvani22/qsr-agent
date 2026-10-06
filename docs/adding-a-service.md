# Adding a QSR Service

[Repository overview](../README.md) | [Documentation guide](index.md) |
[Setup](setup.md) | [Architecture](architecture.md) |
**Add a service**

Adding a domain requires four things, plus optional autonomy events:

1. Create an MCP service with [FastMCP](https://gofastmcp.com).
2. Register it in Hermes.
3. Add its skill file.
4. Verify discovery and one question.
5. Optionally send events to the Operator UI autonomy webhook.

The example below adds an `inventory` service. Replace the names and API fields
for the domain you own.

## 1. Create the MCP service

From the repository root, install FastMCP and create the service file:

```bash
SERVICE_PYTHON=/absolute/path/to/service/venv/bin/python
"$SERVICE_PYTHON" -m pip install "fastmcp>=4.0,<5"
mkdir -p services/inventory
touch services/inventory/service.py
```

Put the domain's API or database access in
`services/inventory/service.py` and expose it as typed MCP tools:

```python
from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastmcp import FastMCP


service = FastMCP("inventory")


@service.tool(
  name="get_inventory_context",
  description="Return the current inventory for one store.",
)
def get_inventory_context(store_id: str) -> dict[str, Any]:
  base_url = os.environ["INVENTORY_API_URL"].rstrip("/")
  request = Request(
    f"{base_url}/v1/stores/{quote(store_id, safe='')}/inventory",
    headers={
      "Accept": "application/json",
      "Authorization": f"Bearer {os.environ['INVENTORY_API_TOKEN']}",
    },
  )
  with urlopen(request, timeout=10) as response:
    result = json.load(response)

  return {
    "source": "inventory-api",
    "store_id": store_id,
    "observed_at": result["observed_at"],
    "items": result["items"],
  }


if __name__ == "__main__":
  service.run()  # stdio; use service.run("http", host=..., port=...) for remote
```

Dict return values are sent as structured content, which the autonomy client
requires. For a tool that changes a source system, enforce approval in the
service, not in the skill. The simulated services use
`tests/mcp-services/service_base.py` for this: `QsrService.act_tool` registers
an action with a `GateLevel` (`automatic`, `notify`, `needs_approval`,
`blocked`) and optional rate limit, and every call goes through its
`PolicyGate`. See [Architecture](architecture.md#responsibility-boundaries)
for those production rules.

### Event-producing services

Services that should trigger autonomous assessments POST an event to the
Operator UI webhook; see [section 5](#5-send-autonomy-events-optional).

## 2. Register the MCP service

Add the service to `~/.hermes/config.yaml`:

```yaml
platform_toolsets:
  cli:
    - inventory

mcp_servers:
  inventory:
    command: /absolute/path/to/qsr-agentic-svc/.venv/bin/python
    args:
      - /absolute/path/to/qsr-agentic-svc/services/inventory/service.py
    env:
      INVENTORY_API_URL: ${INVENTORY_API_URL}
      INVENTORY_API_TOKEN: ${INVENTORY_API_TOKEN}
    enabled: true
```

Use absolute paths. Export credentials before starting Hermes; do not put
literal secrets in the YAML. For a remote service, replace `command`, `args`,
and `env` with its authenticated `url` entry.

## 3. Add the skill

Create `qsr-skills/inventory/SKILL.md`:

```markdown
---
name: inventory
description: "Answer inventory and availability questions using the Inventory MCP service."
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [QSR, Inventory]
---

# Inventory

Use `get_inventory_context` for current inventory questions.

- Pass the requested `store_id`.
- Report `items` and `observed_at` from the tool result.
- Do not invent quantities or answer historical questions from a current result.
```

The repository skill directory is already loaded when this exists in Hermes
configuration:

```yaml
skills:
  external_dirs:
    - /absolute/path/to/qsr-agentic-svc/qsr-skills
```

Keep the skill limited to when the tools should be called and how returned
fields should be interpreted.

## 4. Verify

Restart Hermes, then run:

```bash
export INVENTORY_API_URL=http://127.0.0.1:8080
export INVENTORY_API_TOKEN=replace-with-local-test-token

hermes mcp test inventory
hermes skills list --enabled-only
hermes -z 'What inventory is available at store-001?' --cli -t inventory
```

The service is integrated when Hermes discovers `get_inventory_context`, loads
the `inventory` skill, calls the tool, and answers from its returned fields.

## 5. Send autonomy events (optional)

To have Hermes assess a domain change and propose an action, POST an event to
the Operator UI with a globally unique `event_id`:

```bash
curl -sS -X POST http://127.0.0.1:8600/autonomy/events \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "inventory-store-001-ITEM-42-stockout-123",
    "event_type": "inventory_alert",
    "store_id": "qsr-001",
    "occurred_at": "2026-09-21T12:00:00Z",
    "data": {"item_id": "ITEM-42", "severity": "critical"}
  }'
```

The request returns HTTP 202 once the event is queued. Results, including any
proposal awaiting approval, appear in the right-side **Autonomy decisions**
panel. Retry delivery failures with the same `event_id`; duplicates are ignored.
The [weather-simulator](https://github.com/unarayan/weather-simulator) service
is a working producer. See [Autonomous decisions](autonomy.md) for the
capabilities and skills Hermes needs to act on a new event type.

---

[Previous: Architecture](architecture.md) |
[Documentation guide](index.md)