from __future__ import annotations

import sqlite3
from pathlib import Path

from toolrampart import policy, rate_limit, scope, side_effects, tool

DB_PATH = Path("example.db")


def _is_select_only(ctx, args):
    query = args["query"].strip().lower()
    if not query.startswith("select"):
        return "only SELECT queries are allowed"
    blocked = ["insert", "update", "delete", "drop", "alter", "pragma", "attach"]
    if any(token in query for token in blocked):
        return "query contains a blocked SQL operation"
    return True


@tool
@scope("database.read")
@side_effects(read_only=True, idempotent=True)
@rate_limit("60/hour/user")
@policy(_is_select_only)
def run_read_only_query(query: str, limit: int = 25) -> dict:
    safe_limit = min(max(limit, 1), 100)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchmany(safe_limit)
    return {"rows": [dict(row) for row in rows], "limit": safe_limit}
