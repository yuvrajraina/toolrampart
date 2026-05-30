# Idempotency

Idempotency keys prevent duplicate side effects when agents or clients retry write operations.

```python
result = client.invoke(
    "refund_user",
    {"user_id": "u_1", "amount": 100, "reason": "duplicate"},
    idempotency_key="refund-u_1-001",
)
```

REST callers can send:

- `Idempotency-Key`
- `X-Idempotency-Key`
- `idempotency_key` in the JSON body

The key is scoped by:

- tool name
- actor
- key

If the same actor/tool/key/arguments are used again, ToolRampart replays the stored result with `replayed: true`.

If the same key is reused with different arguments, ToolRampart returns `idempotency_conflict`.
