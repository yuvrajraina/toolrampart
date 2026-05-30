# Isolated Long Job

Use subprocess isolation when timeout termination matters.

Source: `examples/isolated_long_job.py`

```python
from toolrampart import isolated_process, scope, side_effects, timeout, tool

@tool
@scope("jobs.run")
@isolated_process
@timeout(10)
@side_effects(idempotent=True)
def rebuild_search_index(index_name: str, delay_seconds: float = 1.0) -> dict:
    ...
```

The function must be importable at module top level, and arguments and return values must be pickleable.
