from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from .audit import AuditLog


class AuditStore(Protocol):
    def log_event(self, **kwargs: Any) -> str: ...
    def list_events(self, limit: int = 100) -> list[dict[str, Any]]: ...
    def create_approval_request(self, **kwargs: Any) -> str: ...
    def get_approval_request(self, approval_id: str) -> dict[str, Any] | None: ...
    def list_approval_requests(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...
    def resolve_approval_request(self, **kwargs: Any) -> dict[str, Any] | None: ...
    def start_idempotency_record(self, **kwargs: Any) -> dict[str, Any]: ...
    def complete_idempotency_record(self, **kwargs: Any) -> None: ...
    def prune_events(self, *, before: float) -> int: ...
    def stats(self) -> dict[str, Any]: ...


class RateLimitStore(Protocol):
    def count_rate_events(self, *, tool_name: str, bucket: str, since: float) -> int: ...
    def record_rate_event(self, *, tool_name: str, bucket: str) -> None: ...


class SQLiteAuditStore(AuditLog):
    """Default local storage adapter."""


class PostgresAuditStore:
    """Optional PostgreSQL audit and approval store.

    This adapter intentionally mirrors the SQLite schema and only imports psycopg
    when instantiated, keeping the base package lightweight.
    """

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "PostgresAuditStore requires the 'postgres' extra: "
                "pip install toolrampart[postgres]"
            ) from exc

        self._psycopg = psycopg
        self._jsonb = Jsonb
        self._conn = psycopg.connect(dsn, row_factory=dict_row)
        self._ensure_schema()

    def _ensure_schema(self) -> None:  # pragma: no cover - optional dependency
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    status TEXT NOT NULL,
                    arguments JSONB NOT NULL,
                    result JSONB,
                    error TEXT,
                    started_at DOUBLE PRECISION NOT NULL,
                    ended_at DOUBLE PRECISION NOT NULL,
                    metadata JSONB NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    arguments JSONB NOT NULL,
                    arguments_hash TEXT NOT NULL,
                    requested_at DOUBLE PRECISION NOT NULL,
                    resolved_at DOUBLE PRECISION,
                    resolved_by TEXT,
                    resolution_note TEXT,
                    metadata JSONB NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS rate_events (
                    id BIGSERIAL PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    occurred_at DOUBLE PRECISION NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rate_events_lookup
                ON rate_events (tool_name, bucket, occurred_at)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    id BIGSERIAL PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    key TEXT NOT NULL,
                    arguments_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result JSONB,
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    UNIQUE (tool_name, actor, key)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_idempotency_records_lookup
                ON idempotency_records (tool_name, actor, key)
                """
            )
            self._conn.commit()

    def log_event(self, **kwargs: Any) -> str:  # pragma: no cover - optional dependency
        from uuid import uuid4

        audit_id = str(uuid4())
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_events (
                    id, tool_name, actor, status, arguments, result, error,
                    started_at, ended_at, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    audit_id,
                    kwargs["tool_name"],
                    kwargs["actor"],
                    kwargs["status"],
                    self._jsonb(kwargs["arguments"]),
                    self._jsonb(kwargs.get("result")) if kwargs.get("result") is not None else None,
                    kwargs.get("error"),
                    kwargs["started_at"],
                    kwargs.get("ended_at") or time.time(),
                    self._jsonb(kwargs.get("metadata") or {}),
                ),
            )
            self._conn.commit()
        return audit_id

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:  # pragma: no cover
        with self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM audit_events ORDER BY started_at DESC LIMIT %s",
                (limit,),
            )
            return list(cursor.fetchall())

    def create_approval_request(self, **kwargs: Any) -> str:  # pragma: no cover
        from uuid import uuid4

        from .audit import hash_arguments

        approval_id = str(uuid4())
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO approval_requests (
                    id, tool_name, actor, status, reason, arguments,
                    arguments_hash, requested_at, metadata
                )
                VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                """,
                (
                    approval_id,
                    kwargs["tool_name"],
                    kwargs["actor"],
                    kwargs["reason"],
                    self._jsonb(kwargs["arguments"]),
                    hash_arguments(kwargs["raw_arguments"]),
                    time.time(),
                    self._jsonb(kwargs.get("metadata") or {}),
                ),
            )
            self._conn.commit()
        return approval_id

    def get_approval_request(self, approval_id: str) -> dict[str, Any] | None:  # pragma: no cover
        with self._conn.cursor() as cursor:
            cursor.execute("SELECT * FROM approval_requests WHERE id = %s", (approval_id,))
            return cursor.fetchone()

    def list_approval_requests(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:  # pragma: no cover
        with self._conn.cursor() as cursor:
            if status:
                cursor.execute(
                    """
                    SELECT * FROM approval_requests
                    WHERE status = %s
                    ORDER BY requested_at DESC
                    LIMIT %s
                    """,
                    (status, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM approval_requests
                    ORDER BY requested_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            return list(cursor.fetchall())

    def resolve_approval_request(self, **kwargs: Any) -> dict[str, Any] | None:  # pragma: no cover
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE approval_requests
                SET status = %s, resolved_at = %s, resolved_by = %s, resolution_note = %s
                WHERE id = %s AND status = 'pending'
                """,
                (
                    kwargs["status"],
                    time.time(),
                    kwargs["resolved_by"],
                    kwargs.get("note"),
                    kwargs["approval_id"],
                ),
            )
            self._conn.commit()
        return self.get_approval_request(kwargs["approval_id"])

    def start_idempotency_record(self, **kwargs: Any) -> dict[str, Any]:  # pragma: no cover
        from .audit import hash_arguments

        arguments_hash = hash_arguments(kwargs["arguments"])
        now = time.time()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM idempotency_records
                WHERE tool_name = %s AND actor = %s AND key = %s
                """,
                (kwargs["tool_name"], kwargs["actor"], kwargs["key"]),
            )
            row = cursor.fetchone()
            if row is not None:
                if row["arguments_hash"] != arguments_hash:
                    return {"state": "conflict", "record": row}
                if row["status"] == "completed":
                    return {"state": "replay", "record": row}
                return {"state": "in_progress", "record": row}

            cursor.execute(
                """
                INSERT INTO idempotency_records (
                    tool_name, actor, key, arguments_hash, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, 'in_progress', %s, %s)
                RETURNING *
                """,
                (
                    kwargs["tool_name"],
                    kwargs["actor"],
                    kwargs["key"],
                    arguments_hash,
                    now,
                    now,
                ),
            )
            row = cursor.fetchone()
            self._conn.commit()
        return {"state": "started", "record": row}

    def complete_idempotency_record(self, **kwargs: Any) -> None:  # pragma: no cover
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE idempotency_records
                SET status = 'completed', result = %s, updated_at = %s
                WHERE tool_name = %s AND actor = %s AND key = %s
                """,
                (
                    self._jsonb(kwargs["result"]),
                    time.time(),
                    kwargs["tool_name"],
                    kwargs["actor"],
                    kwargs["key"],
                ),
            )
            self._conn.commit()

    def prune_events(self, *, before: float) -> int:  # pragma: no cover
        with self._conn.cursor() as cursor:
            cursor.execute("DELETE FROM audit_events WHERE started_at < %s", (before,))
            deleted = cursor.rowcount
            self._conn.commit()
        return int(deleted)

    def stats(self) -> dict[str, Any]:  # pragma: no cover
        with self._conn.cursor() as cursor:
            cursor.execute("SELECT status, COUNT(*) AS count FROM audit_events GROUP BY status")
            audit = {row["status"]: int(row["count"]) for row in cursor.fetchall()}
            cursor.execute("SELECT status, COUNT(*) AS count FROM approval_requests GROUP BY status")
            approvals = {row["status"]: int(row["count"]) for row in cursor.fetchall()}
        return {"audit_events": audit, "approval_requests": approvals}

    def count_rate_events(self, *, tool_name: str, bucket: str, since: float) -> int:  # pragma: no cover
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM rate_events
                WHERE tool_name = %s AND bucket = %s AND occurred_at >= %s
                """,
                (tool_name, bucket, since),
            )
            row = cursor.fetchone()
        return int(row["count"])

    def record_rate_event(self, *, tool_name: str, bucket: str) -> None:  # pragma: no cover
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rate_events (tool_name, bucket, occurred_at)
                VALUES (%s, %s, %s)
                """,
                (tool_name, bucket, time.time()),
            )
            self._conn.commit()


class RedisRateLimitStore:
    """Optional Redis sorted-set rate-limit store."""

    def __init__(self, url: str) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "RedisRateLimitStore requires the 'redis' extra: "
                "pip install toolrampart[redis]"
            ) from exc

        self._client = redis.Redis.from_url(url, decode_responses=True)

    def _key(self, tool_name: str, bucket: str) -> str:
        return f"toolrampart:rate:{tool_name}:{bucket}"

    def count_rate_events(self, *, tool_name: str, bucket: str, since: float) -> int:
        key = self._key(tool_name, bucket)
        self._client.zremrangebyscore(key, 0, since)
        return int(self._client.zcount(key, since, "+inf"))

    def record_rate_event(self, *, tool_name: str, bucket: str) -> None:
        key = self._key(tool_name, bucket)
        now = time.time()
        self._client.zadd(key, {str(now): now})
        self._client.expire(key, 86400)


def create_audit_store(storage_url: str | None, audit_path: str | Path | None = None) -> AuditStore:
    if not storage_url or storage_url.startswith("sqlite://"):
        path: str | Path | None = audit_path
        if storage_url and storage_url != "sqlite://":
            path = storage_url.removeprefix("sqlite:///")
        return SQLiteAuditStore(path)

    if storage_url.startswith(("postgres://", "postgresql://")):
        return PostgresAuditStore(storage_url)

    raise ValueError(f"unsupported ToolRampart storage URL: {storage_url}")


def create_rate_limit_store(redis_url: str | None) -> RateLimitStore | None:
    if not redis_url:
        return None
    if redis_url.startswith("redis://") or redis_url.startswith("rediss://"):
        return RedisRateLimitStore(redis_url)
    raise ValueError(f"unsupported ToolRampart Redis URL: {redis_url}")
