# Safety Model

ToolRampart controls whether a Python tool function is allowed to run.

It does not replace least-privilege service credentials, network controls, or application-specific checks inside the tool function.

## Execution Pipeline

Every tool call follows this path:

1. Validate input from the function signature.
2. Verify the actor has required scopes.
3. Run custom policy functions.
4. Create or verify approval records.
5. Check idempotency keys.
6. Enforce rate limits.
7. Execute with timeout, retry, and optional isolation.
8. Validate output if the return type is annotated.
9. Redact sensitive fields in audit logs.
10. Store audit events.

## Trust Boundary

For local development, actor and scopes may be supplied in the request body.

For production, enable auth. When auth is enabled, ToolRampart derives actor and scopes from API keys, JWTs, JWKS, or trusted upstream headers.

## What ToolRampart Does Not Do

- It does not build agents.
- It does not host a chatbot.
- It does not sandbox arbitrary production effects by default.
- It does not make unsafe credentials safe.

Use ToolRampart as the control layer around your tools, then still design each tool with least privilege.
