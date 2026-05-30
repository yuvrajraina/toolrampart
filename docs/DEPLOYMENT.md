# Deployment

## Local Docker Compose

Start ToolRampart with Postgres audit storage and Redis rate limiting:

```bash
docker compose up --build
```

Open:

- API: `http://localhost:8000`
- Dashboard: `http://localhost:8000/dashboard`
- OpenAPI: `http://localhost:8000/docs`

The Compose stack runs:

- `toolrampart`
- `postgres`
- `redis`

The API service loads `examples.refund_tool` and uses `examples/toolrampart.compose.toml`.

## Production Notes

- Set `auth.required = true`.
- Use hashed API keys or JWT/JWKS auth.
- Put the service behind TLS.
- Use Postgres for durable audit and approval storage.
- Use Redis for shared rate limits.
- Send idempotency keys for write tools.
- Use `@isolated_process` for risky tools that need killable timeouts.
- Configure OpenTelemetry SDK/exporters in the host process.

## Environment Overrides

Compose also sets:

```bash
TOOLRAMPART_STORAGE_URL=postgresql://toolrampart:toolrampart@postgres:5432/toolrampart
TOOLRAMPART_REDIS_URL=redis://redis:6379/0
```
