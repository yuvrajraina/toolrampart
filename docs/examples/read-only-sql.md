# Read-only SQL Tool

Use this pattern when agents need database visibility but must not mutate data.

Source: `examples/read_only_sql_tool.py`

```python
from toolrampart import policy, rate_limit, scope, side_effects, tool

def _is_select_only(ctx, args):
    query = args["query"].strip().lower()
    if not query.startswith("select"):
        return "only SELECT queries are allowed"
    return True

@tool
@scope("database.read")
@side_effects(read_only=True, idempotent=True)
@rate_limit("60/hour/user")
@policy(_is_select_only)
def run_read_only_query(query: str, limit: int = 25) -> dict:
    ...
```

Use a read-only database user in production. Do not rely on string checks as the only database safety boundary.
