# Python Client

ToolRampart includes a small synchronous HTTP client.

```python
from toolrampart import ToolRampartClient

with ToolRampartClient("http://localhost:8000", api_key="dev-secret") as client:
    result = client.invoke(
        "refund_user",
        {"user_id": "u_1", "amount": 100, "reason": "duplicate"},
        idempotency_key="refund-u_1-001",
    )

    if result.approval_required:
        client.approve(result.approval_id, actor="alice")
```

Methods:

- `health()`
- `tools()`
- `mcp_tools()`
- `invoke(...)`
- `approvals(status=None, limit=100)`
- `approve(approval_id, actor="client", note=None)`
- `reject(approval_id, actor="client", note=None)`
- `audit(limit=100)`
- `metrics()`

Authentication:

```python
ToolRampartClient("https://toolrampart.internal", api_key="...")
ToolRampartClient("https://toolrampart.internal", bearer_token="...")
```

For write tools, pass `idempotency_key` to make retries safe.
