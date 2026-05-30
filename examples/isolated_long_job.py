from __future__ import annotations

import hashlib
import time

from toolrampart import isolated_process, scope, side_effects, timeout, tool


@tool
@scope("jobs.run")
@isolated_process
@timeout(10)
@side_effects(idempotent=True)
def rebuild_search_index(index_name: str, delay_seconds: float = 1.0) -> dict:
    time.sleep(delay_seconds)
    digest = hashlib.sha256(index_name.encode("utf-8")).hexdigest()[:12]
    return {"index_name": index_name, "status": "rebuilt", "digest": digest}
