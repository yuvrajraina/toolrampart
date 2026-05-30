# Destructive Admin Policy

Use this pattern for destructive tools that should be difficult to call accidentally.

Source: `examples/destructive_admin_tool.py`

```python
from toolrampart import policy, require_approval, scope, side_effects, tool

def require_break_glass(ctx, args):
    if ctx.metadata.get("break_glass") is True and args["confirm"] == "DELETE":
        return True
    return "destructive action requires break_glass metadata and confirm='DELETE'"

@tool
@scope("admin.account.delete")
@require_approval()
@policy(require_break_glass)
@side_effects(destructive=True, writes_data=True)
def delete_account(account_id: str, confirm: str) -> dict:
    ...
```

Combine approvals with least-privilege credentials and an internal incident workflow.
