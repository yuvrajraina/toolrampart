# ToolRampart

**FastAPI for safe AI tools.**

ToolRampart is an open-source Python framework for exposing normal Python functions as safe AI-agent tools and MCP-compatible tools.

It helps teams give agents useful capabilities without giving them unrestricted production access.

## Why ToolRampart

AI agents need tools. Production systems need guardrails.

ToolRampart sits between an agent and your Python functions:

1. Validate input with Pydantic.
2. Check actor scopes.
3. Run policy functions.
4. Require approval for risky calls.
5. Deduplicate retries with idempotency keys.
6. Enforce rate limits.
7. Execute with timeouts, retries, and optional subprocess isolation.
8. Validate outputs.
9. Emit audit logs and optional OpenTelemetry signals.

## Install

```bash
pip install toolrampart
```

Optional integrations:

```bash
pip install "toolrampart[all]"
```

## Minimal Tool

```python
from toolrampart import require_approval, scope, tool

@tool
@scope("billing.refund")
@require_approval(over_amount=500)
def refund_user(user_id: str, amount: float, reason: str) -> dict:
    return {"status": "refund_started", "user_id": user_id}
```

Run it:

```bash
toolrampart serve my_tools
```

## Best Starting Points

- [Quickstart](quickstart.md)
- [Safety Model](concepts/safety-model.md)
- [Python Client](CLIENT.md)
- [MCP](MCP.md)
- [Deployment](DEPLOYMENT.md)
- [For AI Agents](agents.md)
