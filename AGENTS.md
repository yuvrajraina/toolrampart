# ToolRampart Agent Instructions

These instructions are for AI coding agents working in this repository.

## Project Identity

ToolRampart is:

- FastAPI for safe AI tools.
- A Python framework for exposing functions as safe AI-agent and MCP-compatible tools.
- A safety layer for validation, authorization, approval, idempotency, rate limiting, isolation, audit, and observability.

ToolRampart is not:

- a chatbot framework
- a full agent framework
- a LangChain replacement

## Best Files To Read First

1. `README.md`
2. `docs/quickstart.md`
3. `docs/concepts/safety-model.md`
4. `docs/THREAT_MODEL.md`
5. `docs/PRODUCTION_CHECKLIST.md`
6. `toolrampart/core.py`
7. `toolrampart/app.py`
8. `toolrampart/client.py`

## Coding Rules

- Keep the package small and developer-first.
- Do not add a full agent runtime.
- Preserve the execution pipeline in `ToolRampart.execute`.
- Tests should cover safety behavior, not just happy paths.
- Optional integrations should remain optional extras.
- Do not bypass audit logging when adding new execution paths.

## Common Integration Pattern

```python
from toolrampart import require_approval, scope, tool

@tool
@scope("billing.refund")
@require_approval(over_amount=500)
def refund_user(user_id: str, amount: float) -> dict:
    return {"status": "refund_started"}
```

For write tools, use idempotency keys. For dangerous tools, use scopes, approvals, redaction, rate limits, and least-privilege credentials.

## Verification

Run:

```bash
python -m pytest -p no:cacheprovider
python -m compileall -q toolrampart tests examples
python -m mkdocs build --strict
```
