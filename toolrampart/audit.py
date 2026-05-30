from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
import hashlib
from pathlib import Path
from typing import Any

from .migrations import run_sqlite_migrations, sqlite_migration_status


def hash_arguments(arguments: dict[str, Any]) -> str:
    payload = json.dumps(arguments, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditLog:
    """SQLite-backed audit and rate-limit storage."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = Path.cwd() / ".toolrampart" / "audit.db"
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock, self._conn:
            run_sqlite_migrations(self._conn)

    def migration_status(self) -> list[dict[str, int | bool]]:
        with self._lock:
            return sqlite_migration_status(self._conn)

    def log_event(
        self,
        *,
        tool_name: str,
        actor: str,
        status: str,
        arguments: Any,
        result: Any = None,
        error: str | None = None,
        started_at: float,
        ended_at: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        audit_id = str(uuid.uuid4())
        payload = (
            audit_id,
            tool_name,
            actor,
            status,
            self._to_json(arguments),
            self._to_json(result) if result is not None else None,
            error,
            started_at,
            ended_at or time.time(),
            self._to_json(metadata or {}),
        )
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO audit_events (
                    id, tool_name, actor, status, arguments, result, error,
                    started_at, ended_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
        return audit_id

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM audit_events
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def create_approval_request(
        self,
        *,
        tool_name: str,
        actor: str,
        reason: str,
        arguments: dict[str, Any],
        raw_arguments: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        approval_id = str(uuid.uuid4())
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO approval_requests (
                    id, tool_name, actor, status, reason, arguments,
                    arguments_hash, requested_at, metadata
                )
                VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    tool_name,
                    actor,
                    reason,
                    self._to_json(arguments),
                    hash_arguments(raw_arguments),
                    time.time(),
                    self._to_json(metadata or {}),
                ),
            )
        return approval_id

    def get_approval_request(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM approval_requests
                WHERE id = ?
                """,
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_approval(row)

    def list_approval_requests(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status:
            query = """
                SELECT * FROM approval_requests
                WHERE status = ?
                ORDER BY requested_at DESC
                LIMIT ?
            """
            params: tuple[Any, ...] = (status, limit)
        else:
            query = """
                SELECT * FROM approval_requests
                ORDER BY requested_at DESC
                LIMIT ?
            """
            params = (limit,)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_approval(row) for row in rows]

    def resolve_approval_request(
        self,
        *,
        approval_id: str,
        status: str,
        resolved_by: str,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        if status not in {"approved", "rejected"}:
            raise ValueError("approval status must be 'approved' or 'rejected'")

        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE approval_requests
                SET status = ?, resolved_at = ?, resolved_by = ?, resolution_note = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, time.time(), resolved_by, note, approval_id),
            )
        return self.get_approval_request(approval_id)

    def prune_events(self, *, before: float) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM audit_events
                WHERE started_at < ?
                """,
                (before,),
            )
            return int(cursor.rowcount)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            audit_rows = self._conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM audit_events
                GROUP BY status
                """
            ).fetchall()
            approval_rows = self._conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM approval_requests
                GROUP BY status
                """
            ).fetchall()
        return {
            "audit_events": {
                row["status"]: int(row["count"])
                for row in audit_rows
            },
            "approval_requests": {
                row["status"]: int(row["count"])
                for row in approval_rows
            },
        }

    def start_idempotency_record(
        self,
        *,
        tool_name: str,
        actor: str,
        key: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        arguments_hash = hash_arguments(arguments)
        now = time.time()
        with self._lock, self._conn:
            row = self._conn.execute(
                """
                SELECT * FROM idempotency_records
                WHERE tool_name = ? AND actor = ? AND key = ?
                """,
                (tool_name, actor, key),
            ).fetchone()
            if row is not None:
                record = self._row_to_idempotency(row)
                if record["arguments_hash"] != arguments_hash:
                    return {
                        "state": "conflict",
                        "record": record,
                    }
                if record["status"] == "completed":
                    return {
                        "state": "replay",
                        "record": record,
                    }
                return {
                    "state": "in_progress",
                    "record": record,
                }

            self._conn.execute(
                """
                INSERT INTO idempotency_records (
                    tool_name, actor, key, arguments_hash, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'in_progress', ?, ?)
                """,
                (tool_name, actor, key, arguments_hash, now, now),
            )
            row = self._conn.execute(
                """
                SELECT * FROM idempotency_records
                WHERE tool_name = ? AND actor = ? AND key = ?
                """,
                (tool_name, actor, key),
            ).fetchone()
        return {"state": "started", "record": self._row_to_idempotency(row)}

    def complete_idempotency_record(
        self,
        *,
        tool_name: str,
        actor: str,
        key: str,
        result: dict[str, Any],
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE idempotency_records
                SET status = 'completed', result = ?, updated_at = ?
                WHERE tool_name = ? AND actor = ? AND key = ?
                """,
                (
                    self._to_json(result),
                    time.time(),
                    tool_name,
                    actor,
                    key,
                ),
            )

    def count_rate_events(self, *, tool_name: str, bucket: str, since: float) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM rate_events
                WHERE tool_name = ? AND bucket = ? AND occurred_at >= ?
                """,
                (tool_name, bucket, since),
            ).fetchone()
        return int(row["count"])

    def record_rate_event(self, *, tool_name: str, bucket: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO rate_events (tool_name, bucket, occurred_at)
                VALUES (?, ?, ?)
                """,
                (tool_name, bucket, time.time()),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _to_json(value: Any) -> str:
        return json.dumps(value, default=str, sort_keys=True)

    @staticmethod
    def _from_json(value: str | None) -> Any:
        if value is None:
            return None
        return json.loads(value)

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tool_name": row["tool_name"],
            "actor": row["actor"],
            "status": row["status"],
            "arguments": self._from_json(row["arguments"]),
            "result": self._from_json(row["result"]),
            "error": row["error"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "metadata": self._from_json(row["metadata"]),
        }

    def _row_to_approval(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tool_name": row["tool_name"],
            "actor": row["actor"],
            "status": row["status"],
            "reason": row["reason"],
            "arguments": self._from_json(row["arguments"]),
            "arguments_hash": row["arguments_hash"],
            "requested_at": row["requested_at"],
            "resolved_at": row["resolved_at"],
            "resolved_by": row["resolved_by"],
            "resolution_note": row["resolution_note"],
            "metadata": self._from_json(row["metadata"]),
        }

    def _row_to_idempotency(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tool_name": row["tool_name"],
            "actor": row["actor"],
            "key": row["key"],
            "arguments_hash": row["arguments_hash"],
            "status": row["status"],
            "result": self._from_json(row["result"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
