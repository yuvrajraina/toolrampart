# Threat Model

ToolRampart is a policy and audit layer for Python tool execution. It is designed to reduce the risk of giving AI agents callable production capabilities.

It is not a complete sandbox, identity provider, secrets manager, web application firewall, or agent runtime.

## Assets

ToolRampart helps protect:

- Production actions exposed through Python functions.
- Actor identity and authorized scopes.
- Approval decisions.
- Idempotency records for write operations.
- Audit logs containing tool inputs, outputs, status, and metadata.
- Operational limits such as rate limits and timeouts.

## Trust Boundaries

Recommended production boundary:

- A trusted gateway or application authenticates callers.
- ToolRampart receives actor identity and scopes from API key, JWT, JWKS, or trusted middleware.
- Tool functions use least-privilege service credentials.
- External systems enforce their own authorization and safety checks.

Do not trust:

- Actor or scope values sent by untrusted request JSON.
- LLM-generated arguments without validation.
- Tool functions to be harmless simply because they are registered.
- Subprocess isolation as a full container or VM sandbox.

## Primary Threats

| Threat | ToolRampart Control | Required External Control |
| --- | --- | --- |
| Agent tries an unauthorized tool | Scope checks and policies | Correct signed identity and least-privilege scopes |
| Agent repeats a write after retry | Idempotency keys | Idempotent downstream API design |
| Agent triggers destructive action | Approval workflow and side-effect metadata | Human review, limited credentials, downstream authorization |
| Sensitive data enters logs | Redaction rules | Data minimization and secret scanning |
| Agent floods an endpoint | Rate limiting | Gateway/WAF limits and resource quotas |
| Tool hangs or runs too long | Timeouts and subprocess isolation | Worker/container limits |
| Tool code performs unexpected side effects | Policies, approvals, audit | Code review, network controls, least-privilege credentials |
| Compromised API key | Hashed key storage and rotation support | Secret manager, short-lived credentials, monitoring |
| Tampered actor identity | JWT/JWKS auth and trusted-header mode | TLS and trusted proxy configuration |

## Non-Goals

ToolRampart does not:

- Prevent arbitrary Python code inside a tool from touching files, network, or environment variables.
- Make untrusted Python code safe to execute in-process.
- Replace cloud IAM, database permissions, or service-level authorization.
- Provide multi-tenant isolation by itself.
- Verify the truthfulness or intent of LLM-generated content.

## Safe Deployment Pattern

Use separate deployments for different risk tiers:

- Read-only analytics tools with read-only credentials.
- Write tools with idempotency, tight scopes, and audit retention.
- Destructive or money-moving tools with mandatory approval and isolated credentials.

For high-risk tools, combine:

- `@scope`
- `@policy`
- `@require_approval`
- `@rate_limit`
- `@timeout`
- `@isolated_process`
- idempotency keys
- least-privilege downstream credentials

## Alpha Security Expectations

The alpha is intended for developer evaluation and controlled internal pilots. For production use, complete the production checklist and run your own security review of registered tools and deployment topology.

