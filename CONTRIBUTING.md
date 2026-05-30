# Contributing

Thanks for helping make ToolRampart safer and more useful.

## Development

```bash
python -m pip install -e ".[dev,all]"
python -m pytest
```

Run optional Postgres/Redis integration tests by setting:

```bash
TOOLRAMPART_TEST_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/toolrampart
TOOLRAMPART_TEST_REDIS_URL=redis://localhost:6379/0
```

## Pull Requests

- Keep changes focused.
- Add or update tests for behavior changes.
- Update docs for public API, security, or deployment changes.
- Avoid introducing required dependencies for optional integrations.

## Security

Please do not open public issues for vulnerabilities. See `SECURITY.md`.
