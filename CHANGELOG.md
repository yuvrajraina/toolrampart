# Changelog

## 0.2.0

- Added approval workflow, approval records, and approve/reject API and CLI.
- Added API key, hashed API key, JWT, and JWKS auth support.
- Added custom policies, side-effect metadata, timeouts, retries, and output validation.
- Added idempotency keys for safe retries.
- Added subprocess isolation for killable tool execution.
- Added optional OpenTelemetry spans and metrics.
- Added MCP stdio server support.
- Added SQLite migrations, optional Postgres audit storage, and optional Redis rate limits.
- Added dashboard, metrics endpoint, Dockerfile, CI, and documentation.
- Added MkDocs site, AI-agent discovery files, release checklist, threat model, production checklist, and hardened release workflow.
- Added CLI `--args-file` support for shell-safe JSON arguments.
- Added MCP input-schema support for ToolRampart reserved approval and idempotency fields.
- Renamed the project, Python import package, CLI, docs URLs, environment variables, headers, metrics, and distribution to `toolrampart`.

## 0.1.0

- Initial developer API for registering tools with scope, approval, redaction, and rate-limit policies.
- Added FastAPI app, CLI, SQLite audit log, and tests.
