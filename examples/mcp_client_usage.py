from __future__ import annotations

"""
Example MCP arguments for calling a ToolRampart tool.

Actual MCP client setup depends on the host application. The important detail is
that ToolRampart reserves _toolrampart_approval_id and
_toolrampart_idempotency_key inside the MCP tool arguments.
"""

refund_arguments = {
    "user_id": "u_123",
    "amount": 100,
    "reason": "duplicate charge",
    "_toolrampart_idempotency_key": "refund-u_123-001",
}

approved_refund_arguments = {
    **refund_arguments,
    "_toolrampart_approval_id": "approval-request-id",
}
