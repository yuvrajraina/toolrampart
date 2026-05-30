from __future__ import annotations

from toolrampart import rate_limit, redact, require_approval, scope, side_effects, tool

CRM = {
    "cus_123": {"email": "old@example.com", "phone": "+15550000000"},
}


@tool
@scope("crm.contact.update")
@require_approval()
@redact(["email", "phone"])
@rate_limit("20/hour/user")
@side_effects(writes_data=True, idempotent=True)
def update_contact(customer_id: str, email: str | None = None, phone: str | None = None) -> dict:
    contact = CRM.setdefault(customer_id, {})
    if email:
        contact["email"] = email
    if phone:
        contact["phone"] = phone
    return {"customer_id": customer_id, "updated": sorted(contact.keys()), "contact": contact}
