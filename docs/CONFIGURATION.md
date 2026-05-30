# Configuration

Create a starter config:

```bash
toolrampart init
```

Example `toolrampart.toml`:

```toml
[auth]
required = true
trust_headers = false

[auth.api_keys]
"dev-secret" = { actor = "local-agent", scopes = ["billing.refund"] }

[auth.hashed_api_keys]
"prod-key-2026-05" = { actor = "prod-agent", scopes = ["billing.*"], hash = "pbkdf2_sha256$...", active = true }

[execution]
timeout_seconds = 30
max_retries = 1

[storage]
audit_path = ".toolrampart/audit.db"
retention_days = 90
# storage_url = "postgresql://user:pass@localhost:5432/toolrampart"
# redis_url = "redis://localhost:6379/0"

[telemetry]
enabled = true
service_name = "toolrampart"
```

Environment overrides:

- `TOOLRAMPART_AUDIT_PATH`
- `TOOLRAMPART_STORAGE_URL`
- `TOOLRAMPART_REDIS_URL`
- `TOOLRAMPART_JWT_SECRET`
- `TOOLRAMPART_TELEMETRY_ENABLED`

Use `trust_headers = true` only behind middleware or a gateway that strips untrusted incoming identity headers.

For production API keys, generate a random key and store only its hash:

```bash
toolrampart auth generate-key
toolrampart auth hash-key trp_generated_key
```

Keep old hashed key entries during rotation and set `active = false` after clients have moved.

For JWTs, `jwt_secret` enables HS256 verification. `jwt_jwks_url` enables RS256/ES256 verification through JWKS.

Scopes support:

- exact scopes: `billing.refund`
- prefix wildcards: `billing.*`
- global wildcard: `*`

Local SQLite schemas are migrated automatically. Check status with:

```bash
toolrampart migrations status
```

OpenTelemetry uses the API package only. Configure exporters in the host application, then keep `telemetry.enabled = true` to emit ToolRampart spans and metrics.
