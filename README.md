# ToolRampart

ToolRampart is a small Python framework for exposing normal Python functions as safe AI-agent tools and MCP-compatible tools.

Positioning:

- FastAPI for safe AI tools.
- Give agents tools without giving them unrestricted production access.

It is not an agent framework, chatbot framework, or LangChain replacement. It is a developer-first safety layer around tool execution.

## Alpha Status

ToolRampart is currently alpha software. The public API is usable for evaluation, examples, and controlled internal pilots, but production deployments should follow the security notes, threat model, and production checklist in the docs.

## Quick Start

Install:

```bash
pip install toolrampart
```

Documentation site:

```bash
pip install ".[docs]"
mkdocs serve
```

AI agents can start from [`llms.txt`](llms.txt) and [`AGENTS.md`](AGENTS.md).

```python
from toolrampart import tool, require_approval, redact, scope, rate_limit, side_effects

@tool
@scope("billing.refund")
@require_approval(over_amount=500)
@redact(["email", "phone", "api_key"])
@rate_limit("10/hour/user")
@side_effects(money_movement=True, writes_data=True)
def refund_user(user_id: str, amount: float, reason: str) -> dict:
    return {
        "status": "refund_started",
        "user_id": user_id,
        "amount": amount,
        "reason": reason,
    }
```

Run a tool module as an API:

```bash
toolrampart serve my_tools
```

Invoke a tool from Python:

```python
from toolrampart import ToolContext, default_rampart

result = default_rampart.invoke(
    "refund_user",
    {"user_id": "u_123", "amount": 100, "reason": "duplicate charge"},
    ToolContext(actor="support-agent", scopes=["billing.refund"]),
)
```

## What It Does

ToolRampart runs every tool through the same safety pipeline:

1. Validate inputs from the Python function signature with Pydantic v2.
2. Check trusted actor scopes.
3. Run custom policy functions.
4. Create or verify approval requests for risky calls.
5. Enforce local or Redis-backed rate limits.
6. Deduplicate retries with idempotency keys.
7. Execute with timeout, retry, and optional subprocess isolation controls.
8. Validate structured return values when annotated.
9. Emit optional OpenTelemetry spans and metrics.
10. Write redacted audit logs.

## REST API

```python
from toolrampart.app import create_app

app = create_app()
```

Endpoints:

- `GET /health`
- `GET /tools`
- `GET /mcp/tools`
- `POST /tools/{tool_name}/invoke`
- `GET /approvals`
- `POST /approvals/{approval_id}/approve`
- `POST /approvals/{approval_id}/reject`
- `GET /audit`
- `GET /metrics`
- `GET /dashboard`

## CLI

```bash
toolrampart init
toolrampart list tools
toolrampart call refund_user --target tools --args '{"user_id":"u_1","amount":100,"reason":"duplicate"}' --scope billing.refund
toolrampart approvals list --target tools
toolrampart approvals approve APPROVAL_ID --target tools --actor alice
toolrampart call refund_user --target tools --idempotency-key refund-u_1-001 --args '{"user_id":"u_1","amount":100,"reason":"duplicate"}'
toolrampart serve tools
toolrampart mcp tools
```

On shells that make inline JSON awkward, write arguments to a file and use:

```bash
toolrampart call refund_user --target tools --args-file args.json --scope billing.refund
```

## Python Client

```python
from toolrampart import ToolRampartClient

client = ToolRampartClient("http://localhost:8000", api_key="dev-secret")

result = client.invoke(
    "refund_user",
    {"user_id": "u_1", "amount": 100, "reason": "duplicate"},
    idempotency_key="refund-u_1-001",
)

if result.approval_required:
    client.approve(result.approval_id, actor="alice")
```

## Auth Boundary

REST auth is optional for local development and should be enabled for shared or production use.

ToolRampart supports:

- API keys through `Authorization: Bearer <key>` or `X-ToolRampart-Key`
- hashed API keys for production configuration and key rotation
- HS256 JWTs with signed actor and scopes
- JWKS-backed JWT verification for RS256/ES256 tokens
- trusted upstream headers: `X-ToolRampart-Actor` and `X-ToolRampart-Scopes`

When auth is enabled, the REST request body cannot grant actor identity or scopes. Those come from the authenticator or trusted middleware.

Generate and hash API keys:

```bash
toolrampart auth generate-key
toolrampart auth hash-key trp_example_secret
```

Scopes support exact matches, `*`, and prefix wildcards such as `billing.*`.

## Idempotency

Use idempotency keys for write tools so agent retries do not duplicate side effects:

```python
from toolrampart import ToolContext, default_rampart

result = default_rampart.invoke(
    "refund_user",
    {"user_id": "u_1", "amount": 100, "reason": "duplicate"},
    ToolContext(actor="agent", scopes=["billing.refund"], idempotency_key="refund-u_1-001"),
)
```

For REST, send `Idempotency-Key` or `X-Idempotency-Key`. ToolRampart replays the completed `ToolResult` when the same actor/tool/key/arguments are seen again, and returns `idempotency_conflict` if the key is reused with different arguments.

## Subprocess Isolation

Use subprocess isolation for risky or long-running tools that need killable timeouts:

```python
from toolrampart import isolated_process, timeout, tool

@tool
@isolated_process
@timeout(5)
def rebuild_index(index_name: str) -> dict:
    return {"status": "rebuilt", "index_name": index_name}
```

The function and return value must be pickleable, and the function should be importable at module top level. Closures, local functions, live database clients, and open sockets do not cross a process boundary safely.

## OpenTelemetry

Install:

```bash
pip install toolrampart[otel]
```

ToolRampart uses the OpenTelemetry API only. Host applications remain responsible for configuring SDK providers and exporters. When available, ToolRampart emits:

- `toolrampart.tool.invoke` spans
- `toolrampart.tool.invocations` counter
- `toolrampart.tool.duration` histogram

## MCP

Install MCP support:

```bash
pip install toolrampart[mcp]
```

Run a stdio MCP server:

```bash
TOOLRAMPART_MCP_SCOPES=billing.refund toolrampart mcp tools
```

ToolRampart uses the official MCP Python SDK as an optional dependency and keeps its own execution pipeline for validation, approvals, rate limits, and audit logging.

## Storage

SQLite is the default storage backend and is intended for local development and single-node deployments.

Optional adapters:

- `toolrampart[postgres]` for PostgreSQL audit and approval storage
- `toolrampart[redis]` for Redis-backed rate limiting
- `toolrampart[otel]` for OpenTelemetry API instrumentation
- `toolrampart[all]` for MCP, OpenTelemetry, Postgres, and Redis extras

SQLite uses an explicit migration runner. Check local schema state with:

```bash
toolrampart migrations status
```

The CI workflow includes service-container integration tests for Postgres and Redis.

## Docker Compose

Run ToolRampart with Postgres and Redis:

```bash
docker compose up --build
```

Then open `http://localhost:8000/dashboard`.

## Current Boundaries

ToolRampart controls whether a tool function is called. It does not magically sandbox all side effects inside the function. For dangerous tools, combine ToolRampart with least-privilege service credentials, network controls, execution timeouts, and approval workflows.

## Release Readiness

Before publishing an alpha, run the release checklist in `docs/RELEASE.md`. The short version is:

```bash
python -m pip install -e ".[dev,docs]"
python -m pytest
python -m mkdocs build --strict
python -m build
python -m twine check dist/*
```
