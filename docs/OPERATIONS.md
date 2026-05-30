# Operations

## Idempotency

Send an idempotency key for write tools:

```bash
toolrampart call refund_user \
  --target tools \
  --idempotency-key refund-u_1-001 \
  --args '{"user_id":"u_1","amount":100,"reason":"duplicate"}' \
  --scope billing.refund
```

On shells where inline JSON is awkward, put the arguments in `args.json` and pass `--args-file args.json`.

REST callers can send:

- `Idempotency-Key`
- `X-Idempotency-Key`
- `idempotency_key` in the JSON body

The key is scoped by tool and actor. Reusing a key with the same arguments replays the stored result. Reusing it with different arguments returns `idempotency_conflict`.

## Subprocess Isolation

Use subprocess isolation for tools where timeout termination matters:

```python
from toolrampart import isolated_process, timeout, tool

@tool
@isolated_process
@timeout(10)
def run_report(report_id: str) -> dict:
    return {"report_id": report_id, "status": "complete"}
```

Requirements:

- The function must be importable at module top level.
- Arguments and return values must be pickleable.
- Create external clients inside the function, not outside it.
- Do not rely on in-memory global state shared with the parent process.

## OpenTelemetry

Install:

```bash
pip install toolrampart[otel]
```

ToolRampart uses the installed package version for instrumentation scope metadata:

- `trace.get_tracer("toolrampart", toolrampart.__version__)`
- `metrics.get_meter("toolrampart", toolrampart.__version__)`

It does not configure exporters. Configure the OpenTelemetry SDK in your application, then ToolRampart will emit spans and metrics through the global providers.
