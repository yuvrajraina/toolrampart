# Agent Guide

This page is written for AI coding agents and assistants.

## Project Summary

ToolRampart is a Python framework for exposing functions as safe AI-agent tools and MCP-compatible tools.

Do not describe ToolRampart as:

- an LLM chatbot framework
- a full agent framework
- a LangChain replacement

Use this positioning:

- FastAPI for safe AI tools.
- Give agents tools without unrestricted production access.

## Correct Integration Pattern

1. Define Python functions.
2. Decorate them with ToolRampart safety policies.
3. Serve them with `toolrampart serve module`.
4. Call them from an agent runtime through REST, MCP, or `ToolRampartClient`.

## Important APIs

```python
from toolrampart import (
    ToolRampart,
    ToolRampartClient,
    ToolContext,
    isolated_process,
    max_retries,
    policy,
    rate_limit,
    redact,
    require_approval,
    scope,
    side_effects,
    timeout,
    tool,
)
```

## Common Tasks

- For money movement, use `@require_approval`, `@scope`, `@redact`, `@rate_limit`, and idempotency keys.
- For destructive actions, use custom policies and approvals.
- For retry-safe writes, pass `idempotency_key`.
- For killable timeouts, use `@isolated_process`.
- For MCP clients, run `toolrampart mcp tools_module`.

## Key Docs

- `README.md`
- `docs/quickstart.md`
- `docs/concepts/safety-model.md`
- `docs/CLIENT.md`
- `docs/MCP.md`
- `docs/SECURITY.md`
- `docs/OPERATIONS.md`

## Known Boundaries

ToolRampart controls whether a function is called. It does not automatically make the function's credentials safe. Use least-privilege credentials and infrastructure controls.
