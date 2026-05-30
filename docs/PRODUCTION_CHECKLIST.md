# Production Checklist

Use this checklist before exposing ToolRampart tools to shared environments or production systems.

## Identity

- Enable `require_auth=True` for REST deployments.
- Use JWT/JWKS or hashed API keys, not plaintext keys in config.
- Do not accept actor or scopes from request JSON at the trust boundary.
- Use trusted headers only behind infrastructure that strips untrusted inbound copies.
- Rotate API keys with overlapping active keys.

## Tool Design

- Give each tool a narrow, explicit scope.
- Declare side effects with `@side_effects`.
- Require approvals for money movement, deletion, permission changes, and external writes.
- Require idempotency keys for write tools.
- Keep tool arguments specific and validateable.
- Use least-privilege credentials inside each tool.

## Runtime Safety

- Set short default execution timeouts.
- Use `@isolated_process` for risky or killable long-running work.
- Keep retry counts low and avoid retries for non-idempotent operations.
- Put resource limits around the hosting worker or container.
- Split read-only and destructive tools into separate services when possible.

## Storage

- Use SQLite only for local development or single-node deployments.
- Use Postgres for durable audit and approval storage in production.
- Use Redis for shared rate limits across multiple workers.
- Back up audit and approval storage.
- Define retention periods for audit logs.

## Observability

- Enable OpenTelemetry providers and exporters in the host application.
- Scrape `/metrics`.
- Alert on high denial, rate-limit, timeout, and error rates.
- Review pending approvals and rejected attempts regularly.
- Log request IDs from upstream gateways into `ToolContext`.

## Network And Secrets

- Terminate TLS before ToolRampart.
- Store secrets in a secret manager or platform secret store.
- Restrict egress for deployments that do not need open networking.
- Give destructive tools separate credentials from read-only tools.
- Keep MCP stdio servers in trusted local environments unless the transport provides auth.

## Release Gates

- Run the full local verification from `docs/RELEASE.md`.
- Review the threat model for changes in the exposed tool set.
- Test at least one successful, denied, approval-required, approved, rate-limited, and idempotent replay path.
- Test rollback by yanking or replacing a staging package release before relying on the process.

