# MCP Client Usage

Run ToolRampart as an MCP server:

```bash
TOOLRAMPART_MCP_SCOPES=billing.refund toolrampart mcp examples.refund_tool
```

ToolRampart reserves these MCP argument keys:

- `_toolrampart_approval_id`
- `_toolrampart_idempotency_key`

Example arguments:

```python
{
    "user_id": "u_123",
    "amount": 100,
    "reason": "duplicate charge",
    "_toolrampart_idempotency_key": "refund-u_123-001",
}
```

If a call returns `requires_approval`, approve the request and retry with:

```python
{
    "_toolrampart_approval_id": "approval-request-id"
}
```
