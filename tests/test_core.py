from __future__ import annotations

import os
import time
from pathlib import Path

from toolrampart import (
    ToolRampart,
    ToolContext,
    hash_api_key,
    isolated_process,
    max_retries,
    policy,
    rate_limit,
    redact,
    require_approval,
    scope,
    side_effects,
    timeout,
    verify_api_key,
)
from toolrampart.audit import AuditLog
from toolrampart.telemetry import Telemetry


def subprocess_echo_pid(marker_path: str) -> dict:
    pid = os.getpid()
    Path(marker_path).write_text(str(pid), encoding="utf-8")
    return {"pid": pid}


def subprocess_slow() -> dict:
    time.sleep(5)
    return {"ok": True}


def test_scope_approval_redaction_and_audit(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")
    calls = []

    @shield.tool
    @scope("billing.refund")
    @require_approval(over_amount=500)
    @redact(["api_key", "email"])
    def refund_user(user_id: str, amount: float, email: str, api_key: str) -> dict:
        calls.append(user_id)
        return {"status": "refund_started", "email": email, "amount": amount}

    denied = shield.invoke(
        "refund_user",
        {"user_id": "u_1", "amount": 100, "email": "a@example.com", "api_key": "secret"},
        ToolContext(actor="agent"),
    )
    assert denied.status == "denied"
    assert calls == []

    needs_approval = shield.invoke(
        "refund_user",
        {"user_id": "u_1", "amount": 700, "email": "a@example.com", "api_key": "secret"},
        ToolContext(actor="agent", scopes=["billing.refund"]),
    )
    assert needs_approval.status == "requires_approval"
    assert needs_approval.approval_required is True
    assert calls == []

    approved = shield.invoke(
        "refund_user",
        {"user_id": "u_1", "amount": 700, "email": "a@example.com", "api_key": "secret"},
        ToolContext(actor="agent", scopes=["billing.refund"], approved=True, approved_by="lead"),
    )
    assert approved.status == "success"
    assert approved.data["email"] == "a@example.com"
    assert calls == ["u_1"]

    latest = shield.audit_log.list_events(limit=1)[0]
    assert latest["arguments"]["api_key"] == "[REDACTED]"
    assert latest["arguments"]["email"] == "[REDACTED]"
    assert latest["result"]["email"] == "[REDACTED]"
    assert latest["metadata"]["approved_by"] == "lead"


def test_rate_limit_is_per_tool_and_actor(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @rate_limit("2/hour/user")
    def ping(message: str) -> dict:
        return {"message": message}

    context = ToolContext(actor="agent")
    assert shield.invoke("ping", {"message": "one"}, context).status == "success"
    assert shield.invoke("ping", {"message": "two"}, context).status == "success"

    limited = shield.invoke("ping", {"message": "three"}, context)
    assert limited.status == "rate_limited"
    assert "2/hour/user" in limited.message

    other_actor = shield.invoke("ping", {"message": "fresh"}, ToolContext(actor="other"))
    assert other_actor.status == "success"


def test_validation_prevents_execution(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")
    calls = []

    @shield.tool
    def multiply(count: int) -> int:
        calls.append(count)
        return count * 2

    result = shield.invoke("multiply", {"count": "not-an-int"})
    assert result.status == "validation_error"
    assert calls == []


def test_tool_schema_uses_function_signature(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool(description="Send a message.")
    @side_effects(read_only=False, idempotent=True, external_network=True)
    def send_message(user_id: str, body: str, urgent: bool = False) -> dict:
        return {"sent": True}

    schema = shield.get_tool("send_message").public_schema()
    assert schema["description"] == "Send a message."
    assert set(schema["input_schema"]["required"]) == {"user_id", "body"}
    assert schema["input_schema"]["properties"]["urgent"]["default"] is False
    assert schema["side_effects"]["idempotent"] is True
    assert schema["output_schema"]["type"] == "object"


def test_approval_workflow_requires_matching_approved_request(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")
    calls = []

    @shield.tool
    @require_approval(over_amount=500)
    def refund(amount: float) -> dict:
        calls.append(amount)
        return {"ok": True}

    pending = shield.invoke("refund", {"amount": 700}, ToolContext(actor="agent"))
    assert pending.status == "requires_approval"
    assert pending.approval_id
    assert calls == []

    approvals = shield.list_approvals(status="pending")
    assert approvals[0]["id"] == pending.approval_id
    assert approvals[0]["arguments"] == {"amount": 700.0}

    shield.approve(pending.approval_id, actor="human")
    approved = shield.invoke(
        "refund",
        {"amount": 700},
        ToolContext(actor="agent", approval_id=pending.approval_id),
    )
    assert approved.status == "success"
    assert approved.approval_id == pending.approval_id
    assert calls == [700.0]

    mismatch = shield.invoke(
        "refund",
        {"amount": 800},
        ToolContext(actor="agent", approval_id=pending.approval_id),
    )
    assert mismatch.status == "denied"


def test_custom_policy_can_deny_execution(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @policy(lambda ctx, args: args["amount"] <= 100 or "amount too high")
    def refund(amount: float) -> dict:
        return {"ok": True}

    denied = shield.invoke("refund", {"amount": 101})
    assert denied.status == "denied"
    assert denied.error == "amount too high"


def test_timeout_and_retries(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db", execution_timeout_seconds=0.05)
    attempts = []

    @shield.tool
    @max_retries(2)
    def flaky() -> dict:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("try again")
        return {"ok": True}

    assert shield.invoke("flaky").status == "success"
    assert len(attempts) == 3

    @shield.tool
    @timeout(0.01)
    def slow() -> dict:
        time.sleep(0.05)
        return {"ok": True}

    result = shield.invoke("slow")
    assert result.status == "timeout"


def test_wildcard_scopes_grant_prefixed_access(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @scope("billing.refund")
    def refund() -> dict:
        return {"ok": True}

    result = shield.invoke("refund", context=ToolContext(scopes=["billing.*"]))
    assert result.status == "success"


def test_api_key_hashing_and_migration_status(tmp_path):
    api_key = "trp_test_secret"
    stored_hash = hash_api_key(api_key)
    assert verify_api_key(api_key, stored_hash)
    assert not verify_api_key("wrong", stored_hash)

    audit = AuditLog(tmp_path / "audit.db")
    assert audit.migration_status() == [
        {"version": 1, "applied": True},
        {"version": 2, "applied": True},
    ]


def test_idempotency_replays_completed_result(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")
    calls = []

    @shield.tool
    def create_refund(amount: float) -> dict:
        calls.append(amount)
        return {"refund_id": f"r_{len(calls)}", "amount": amount}

    context = ToolContext(actor="agent", idempotency_key="refund-123")
    first = shield.invoke("create_refund", {"amount": 10}, context)
    assert first.status == "success"
    assert first.replayed is False

    second = shield.invoke(
        "create_refund",
        {"amount": 10},
        ToolContext(actor="agent", idempotency_key="refund-123"),
    )
    assert second.status == "success"
    assert second.replayed is True
    assert second.data == first.data
    assert calls == [10.0]

    conflict = shield.invoke(
        "create_refund",
        {"amount": 20},
        ToolContext(actor="agent", idempotency_key="refund-123"),
    )
    assert conflict.status == "idempotency_conflict"


def test_subprocess_isolation_runs_and_can_timeout(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db", execution_timeout_seconds=5)
    marker = tmp_path / "pid.txt"
    shield.tool(isolated_process(subprocess_echo_pid), name="echo_pid")
    shield.tool(
        isolated_process(subprocess_slow),
        name="slow_subprocess",
        timeout_seconds=0.2,
    )

    result = shield.invoke("echo_pid", {"marker_path": str(marker)})
    assert result.status == "success"
    assert marker.exists()
    assert result.data["pid"] != os.getpid()

    timed_out = shield.invoke("slow_subprocess")
    assert timed_out.status == "timeout"


def test_telemetry_noops_without_sdk():
    telemetry = Telemetry()
    with telemetry.start_tool_span(tool_name="demo", actor="agent", source="test"):
        telemetry.checkpoint("validated")
        telemetry.record_result(
            tool_name="demo",
            status="success",
            duration_seconds=0.01,
        )
