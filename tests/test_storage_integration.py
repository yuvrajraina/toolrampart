from __future__ import annotations

import os
import time
import uuid

import pytest


@pytest.mark.integration
def test_postgres_audit_store_against_real_database():
    postgres_url = os.getenv("TOOLRAMPART_TEST_POSTGRES_URL")
    if not postgres_url:
        pytest.skip("set TOOLRAMPART_TEST_POSTGRES_URL to run Postgres integration test")

    from toolrampart.storage import PostgresAuditStore

    store = PostgresAuditStore(postgres_url)
    tool_name = f"tool_{uuid.uuid4().hex}"
    audit_id = store.log_event(
        tool_name=tool_name,
        actor="integration",
        status="success",
        arguments={"value": 1},
        result={"ok": True},
        started_at=time.time(),
        metadata={},
    )
    assert audit_id
    assert store.list_events(limit=1)[0]["tool_name"] == tool_name

    approval_id = store.create_approval_request(
        tool_name=tool_name,
        actor="integration",
        reason="test",
        arguments={"value": 1},
        raw_arguments={"value": 1},
        metadata={},
    )
    resolved = store.resolve_approval_request(
        approval_id=approval_id,
        status="approved",
        resolved_by="integration",
    )
    assert resolved["status"] == "approved"

    bucket = uuid.uuid4().hex
    assert store.count_rate_events(tool_name=tool_name, bucket=bucket, since=0) == 0
    store.record_rate_event(tool_name=tool_name, bucket=bucket)
    assert store.count_rate_events(tool_name=tool_name, bucket=bucket, since=0) == 1

    started = store.start_idempotency_record(
        tool_name=tool_name,
        actor="integration",
        key="idem-1",
        arguments={"value": 1},
    )
    assert started["state"] == "started"
    store.complete_idempotency_record(
        tool_name=tool_name,
        actor="integration",
        key="idem-1",
        result={"status": "success"},
    )
    replay = store.start_idempotency_record(
        tool_name=tool_name,
        actor="integration",
        key="idem-1",
        arguments={"value": 1},
    )
    assert replay["state"] == "replay"


@pytest.mark.integration
def test_redis_rate_limit_store_against_real_redis():
    redis_url = os.getenv("TOOLRAMPART_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("set TOOLRAMPART_TEST_REDIS_URL to run Redis integration test")

    from toolrampart.storage import RedisRateLimitStore

    store = RedisRateLimitStore(redis_url)
    tool_name = f"tool_{uuid.uuid4().hex}"
    bucket = uuid.uuid4().hex
    assert store.count_rate_events(tool_name=tool_name, bucket=bucket, since=0) == 0
    store.record_rate_event(tool_name=tool_name, bucket=bucket)
    assert store.count_rate_events(tool_name=tool_name, bucket=bucket, since=0) == 1
