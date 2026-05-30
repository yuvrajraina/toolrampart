# Tool Policies

Policies are decorators that describe when and how a tool may run.

```python
from toolrampart import policy, rate_limit, require_approval, scope

@scope("billing.refund")
@require_approval(over_amount=500)
@rate_limit("10/hour/user")
@policy(lambda ctx, args: args["amount"] <= 5000 or "refund exceeds tool maximum")
def refund_user(user_id: str, amount: float, reason: str) -> dict:
    ...
```

## Built-in Policies

- `@scope("billing.refund")`
- `@require_approval(over_amount=500)`
- `@redact(["email", "api_key"])`
- `@rate_limit("10/hour/user")`
- `@timeout(10)`
- `@max_retries(2)`
- `@side_effects(...)`
- `@isolated_process`

## Custom Policies

Custom policies receive the `ToolContext` and validated arguments.

Return:

- `True` or `None` to allow execution
- `False` to deny execution
- a string to deny execution with that message

```python
def only_business_hours(ctx, args):
    return ctx.metadata.get("business_hours") is True or "outside business hours"

@policy(only_business_hours)
def update_customer(customer_id: str, email: str) -> dict:
    ...
```
