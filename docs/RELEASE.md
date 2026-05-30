# Release Process

ToolRampart uses semantic versioning while the API is stabilizing. During alpha, breaking changes can still happen, but they must be documented in the changelog.

## Alpha Release Criteria

Before publishing an alpha:

- The distribution name in `pyproject.toml` is `toolrampart`.
- The version in `pyproject.toml`, `toolrampart/_version.py`, and `CHANGELOG.md` matches.
- `README.md` describes the current public API and known boundaries.
- `docs/SECURITY.md`, `docs/THREAT_MODEL.md`, and `docs/PRODUCTION_CHECKLIST.md` are current.
- Tests pass on the supported Python versions in CI.
- `mkdocs build --strict` passes.
- `python -m build` and `python -m twine check dist/*` pass.
- New public behavior has at least one test or example.

## Local Verification

```bash
python -m pip install -e ".[dev,docs]"
python -m pytest
python -m mkdocs build --strict
python -m build
python -m twine check dist/*
```

Optional integration checks:

```bash
python -m pip install -e ".[all]"
python -m pytest tests/test_mcp_optional.py tests/test_storage_integration.py
docker compose up --build
```

## TestPyPI Dry Run

Use the manual Release workflow with `publish=testpypi`.

After it publishes, test installation in a fresh environment:

```bash
python -m venv .venv-test
.venv-test\Scripts\python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple toolrampart
.venv-test\Scripts\python -c "import toolrampart; print(toolrampart.__version__)"
```

## PyPI Release

1. Confirm the changelog entry is complete.
2. Commit all release changes.
3. Create a signed tag when possible:

```bash
git tag -s v0.2.0 -m "ToolRampart 0.2.0"
git push origin v0.2.0
```

4. The Release workflow builds, checks, and publishes through PyPI trusted publishing.
5. Create a GitHub release using the matching changelog entry.
6. Verify public install:

```bash
python -m pip install toolrampart==0.2.0
toolrampart --help
```

## Rollback

Python package releases cannot be overwritten safely. If a bad alpha is published:

- Yank the broken release on PyPI.
- Publish a patch release with the fix.
- Add a changelog note explaining the issue and replacement version.
