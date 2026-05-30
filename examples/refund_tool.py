from toolrampart import rate_limit, redact, require_approval, scope, side_effects, tool


@tool
@scope("billing.refund")
@require_approval(over_amount=500)
@redact(["email", "phone", "api_key"])
@rate_limit("10/hour/user")
@side_effects(idempotent=False, money_movement=True, writes_data=True)
def refund_user(user_id: str, amount: float, reason: str) -> dict:
    return {
        "status": "refund_started",
        "user_id": user_id,
        "amount": amount,
        "reason": reason,
    }
