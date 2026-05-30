# Security Policy

ToolRampart is security-sensitive software. Please report vulnerabilities privately.

## Reporting

Email: security@yuvrajraina.com

Include:

- affected version or commit
- reproduction steps
- impact
- suggested fix, if known

Please do not publish exploit details until maintainers have investigated and coordinated a fix.

## Scope

Security issues include:

- auth bypass
- approval replay or forgery
- idempotency bypass for write tools
- audit redaction bypass
- dashboard exposure
- MCP trust-boundary issues
- sandbox or subprocess isolation escapes

See `docs/THREAT_MODEL.md` and `docs/PRODUCTION_CHECKLIST.md` for the current security model and deployment assumptions.

## Supported Versions

ToolRampart is pre-1.0. Security fixes target the latest release.
