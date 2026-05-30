# Security Notes

ToolRampart is a safety layer for tool execution, not a sandbox.

Use it to decide whether a tool should run. Use infrastructure controls to limit what the underlying tool can do after it starts.

See also:

- [Threat Model](THREAT_MODEL.md)
- [Production Checklist](PRODUCTION_CHECKLIST.md)
- [Release Process](RELEASE.md)

Recommended production controls:

- Enable API key or JWT auth for REST.
- Store production API keys as ToolRampart hashes, not plaintext config values.
- Rotate keys by adding a new active hashed key before disabling the old one.
- Prefer JWKS-backed RS256/ES256 JWTs for shared production identity systems.
- Do not trust actor or scopes from request JSON.
- Put ToolRampart behind TLS.
- Use least-privilege credentials inside tool functions.
- Split read-only and destructive tools into separate deployments when possible.
- Require approvals for money movement, data deletion, account changes, and external side effects.
- Use short execution timeouts.
- Use `@isolated_process` for risky tools that need killable timeouts.
- Use idempotency keys for money movement, writes, and destructive operations.
- Use Redis for shared rate limits in multi-node deployments.
- Use Postgres for durable audit and approval storage.
- Set an audit retention policy.
- Monitor `/metrics` and review `/audit` regularly.

Current limitations:

- Python threads used for sync tool timeouts cannot be forcibly killed after timeout. Subprocess isolation can terminate the child process, but only for pickleable/importable tools.
- The default SQLite backend is local to one process/node.
- MCP auth should be enforced by the host or transport environment.
- Tool functions need their own least-privilege credentials and input-specific safety checks.
