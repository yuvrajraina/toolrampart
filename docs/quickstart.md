# Quickstart

Create `tools.py`:

```python
from toolrampart import rate_limit, redact, require_approval, scope, side_effects, tool

@tool
@scope("billing.refund")
@require_approval(over_amount=500)
@redact(["email", "phone", "api_key"])
@rate_limit("10/hour/user")
@side_effects(money_movement=True, writes_data=True)
def refund_user(user_id: str, amount: float, reason: str) -> dict:
    return {
        "status": "refund_started",
        "user_id": user_id,
        "amount": amount,
        "reason": reason,
    }
```

Start the API:

```bash
toolrampart serve tools
```

Invoke from Python:

```python
from toolrampart import ToolContext, default_rampart

result = default_rampart.invoke(
    "refund_user",
    {"user_id": "u_123", "amount": 100, "reason": "duplicate charge"},
    ToolContext(
        actor="support-agent",
        scopes=["billing.refund"],
        idempotency_key="refund-u_123-001",
    ),
)
```

Invoke over HTTP:

```python
from toolrampart import ToolRampartClient

client = ToolRampartClient("http://localhost:8000")
result = client.invoke(
    "refund_user",
    {"user_id": "u_123", "amount": 100, "reason": "duplicate charge"},
    actor="support-agent",
    scopes=["billing.refund"],
    idempotency_key="refund-u_123-001",
)
```

Open the dashboard:

```text
http://localhost:8000/dashboard
```
