from __future__ import annotations

from fastapi.testclient import TestClient

from toolrampart import ToolRampart, ToolRampartClient, require_approval, scope
from toolrampart.app import create_app


def _client_for(shield: ToolRampart) -> ToolRampartClient:
    http_client = TestClient(create_app(shield))
    return ToolRampartClient("http://testserver", client=http_client)


def test_client_lists_invokes_and_replays_idempotent_result(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")
    calls = []

    @shield.tool
    @scope("tickets.create")
    def create_ticket(title: str) -> dict:
        calls.append(title)
        return {"ticket_id": f"t_{len(calls)}", "title": title}

    with _client_for(shield) as client:
        assert client.health() == {"status": "ok"}
        assert client.tools()[0]["name"] == "create_ticket"

        first = client.invoke(
            "create_ticket",
            {"title": "hello"},
            actor="agent",
            scopes=["tickets.create"],
            idempotency_key="ticket-1",
        )
        second = client.invoke(
            "create_ticket",
            {"title": "hello"},
            actor="agent",
            scopes=["tickets.create"],
            idempotency_key="ticket-1",
        )

        assert first.ok
        assert second.ok
        assert second.replayed is True
        assert second.data == first.data
        conflict = client.invoke(
            "create_ticket",
            {"title": "different"},
            actor="agent",
            scopes=["tickets.create"],
            idempotency_key="ticket-1",
        )
        assert conflict.status == "idempotency_conflict"
        assert calls == ["hello"]
        assert client.audit(limit=10)
        assert "toolrampart_audit_events_total" in client.metrics()


def test_client_approval_helpers(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @require_approval()
    def dangerous() -> dict:
        return {"ok": True}

    with _client_for(shield) as client:
        pending = client.invoke("dangerous", actor="agent")
        assert pending.status == "requires_approval"
        assert pending.approval_id

        approvals = client.approvals(status="pending")
        assert approvals[0]["id"] == pending.approval_id

        approved = client.approve(pending.approval_id, actor="lead", note="approved")
        assert approved["status"] == "approved"

        result = client.invoke(
            "dangerous",
            actor="agent",
            approval_id=pending.approval_id,
        )
        assert result.ok
