# CRM Update With Approval

Use this pattern for customer data changes.

Source: `examples/crm_update_tool.py`

```python
from toolrampart import rate_limit, redact, require_approval, scope, side_effects, tool

@tool
@scope("crm.contact.update")
@require_approval()
@redact(["email", "phone"])
@rate_limit("20/hour/user")
@side_effects(writes_data=True, idempotent=True)
def update_contact(customer_id: str, email: str | None = None, phone: str | None = None) -> dict:
    ...
```

Call with an idempotency key:

```python
client.invoke(
    "update_contact",
    {"customer_id": "cus_123", "email": "new@example.com"},
    idempotency_key="crm-contact-cus_123-email-001",
)
```
