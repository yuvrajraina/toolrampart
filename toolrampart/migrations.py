from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SQLiteMigration:
    version: int
    apply: Callable[[sqlite3.Connection], None]


def run_sqlite_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        )
        """
    )
    applied = {
        int(row[0])
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for migration in SQLITE_MIGRATIONS:
        if migration.version in applied:
            continue
        migration.apply(conn)
        conn.execute(
            """
            INSERT INTO schema_migrations (version, applied_at)
            VALUES (?, ?)
            """,
            (migration.version, time.time()),
        )
    conn.commit()


def sqlite_migration_status(conn: sqlite3.Connection) -> list[dict[str, int | bool]]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        )
        """
    )
    applied = {
        int(row[0])
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    return [
        {"version": migration.version, "applied": migration.version in applied}
        for migration in SQLITE_MIGRATIONS
    ]


def _migration_1_initial_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            tool_name TEXT NOT NULL,
            actor TEXT NOT NULL,
            status TEXT NOT NULL,
            arguments TEXT NOT NULL,
            result TEXT,
            error TEXT,
            started_at REAL NOT NULL,
            ended_at REAL NOT NULL,
            metadata TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_requests (
            id TEXT PRIMARY KEY,
            tool_name TEXT NOT NULL,
            actor TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            arguments TEXT NOT NULL,
            arguments_hash TEXT NOT NULL,
            requested_at REAL NOT NULL,
            resolved_at REAL,
            resolved_by TEXT,
            resolution_note TEXT,
            metadata TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            bucket TEXT NOT NULL,
            occurred_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rate_events_lookup
        ON rate_events (tool_name, bucket, occurred_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_approval_requests_status
        ON approval_requests (status, requested_at)
        """
    )


def _migration_2_idempotency_records(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS idempotency_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            actor TEXT NOT NULL,
            key TEXT NOT NULL,
            arguments_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            result TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE (tool_name, actor, key)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_idempotency_records_lookup
        ON idempotency_records (tool_name, actor, key)
        """
    )


SQLITE_MIGRATIONS = [
    SQLiteMigration(1, _migration_1_initial_schema),
    SQLiteMigration(2, _migration_2_idempotency_records),
]
