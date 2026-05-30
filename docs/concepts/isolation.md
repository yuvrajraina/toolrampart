# Subprocess Isolation

Use subprocess isolation for risky tools that need killable timeouts.

```python
from toolrampart import isolated_process, timeout, tool

@tool
@isolated_process
@timeout(10)
def run_report(report_id: str) -> dict:
    return {"report_id": report_id, "status": "complete"}
```

## Requirements

- The function must be importable at module top level.
- Arguments must be pickleable.
- Return values must be pickleable.
- Create external clients inside the function.
- Do not depend on in-memory state from the parent process.

## When To Use It

Use subprocess isolation for:

- long-running jobs
- data processing
- risky admin operations
- tools with strict timeout requirements

For simple read-only tools, normal thread execution is usually enough.
