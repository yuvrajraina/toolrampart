## Summary

Describe the change.

## Safety Impact

- [ ] Changes tool execution behavior
- [ ] Changes auth, approval, idempotency, redaction, or audit behavior
- [ ] Changes docs/examples only

## Verification

```bash
python -m pytest -p no:cacheprovider
python -m compileall -q agentshield tests examples
```
