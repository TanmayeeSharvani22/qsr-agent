# Adding a QSR Service

[Repository overview](../README.md) | [Documentation guide](index.md) |
[Setup](setup.md) | [Architecture](architecture.md) |
**Add a service**

Adding a domain requires four things:

1. Create an MCP service with `mcp-service-sdk`.
2. Register it in Hermes.
3. Add its skill file.
4. Verify discovery and one question.

The example below adds an `inventory` service. Replace the names and API fields
for the domain you own.

## 1. Create the MCP service

From the repository root, install the shared base and create the service file:

```bash
SERVICE_PYTHON=/absolute/path/to/service/venv/bin/python
"$SERVICE_PYTHON" -m pip install "mcp-service-sdk[mcp] @ git+https://github.com/sachinkaushik/edge-ai-libraries.git@<tag-or-branch>#subdirectory=libraries/mcp-service-sdk"
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

from mcp_service_sdk import ServiceServer


service = ServiceServer(service="inventory", store_id="multi-store")


@service.read_tool(
  "get_inventory_context",
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
  service.run()
```

Use `@service.read_tool` for reads. For a tool that changes a source system,
use `@service.act_tool` with a `GateLevel` and enforce approval in the service,
not in the skill. See [Architecture](architecture.md#responsibility-boundaries)
for those production rules.

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

---

[Previous: Architecture](architecture.md) |
[Documentation guide](index.md)