# Approvals

Approval policies prevent high-risk calls from executing until a human approves them.

```python
from toolrampart import require_approval, tool

@tool
@require_approval(over_amount=500)
def refund_user(user_id: str, amount: float) -> dict:
    ...
```

If `amount > 500`, ToolRampart returns:

```json
{
  "status": "requires_approval",
  "approval_required": true,
  "approval_id": "..."
}
```

Approve with the CLI:

```bash
toolrampart approvals approve APPROVAL_ID --target tools --actor alice
```

Approve with the client:

```python
client.approve(approval_id, actor="alice")
```

Then retry with the same `approval_id`.

ToolRampart checks that the approval belongs to the same tool and arguments.
