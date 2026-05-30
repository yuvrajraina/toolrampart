from __future__ import annotations

from fastapi.testclient import TestClient

from toolrampart import ToolRampart, hash_api_key, scope
from toolrampart.app import create_app
from toolrampart.auth import APIKeyAuthenticator, HashedAPIKeyAuthenticator, JWKSAuthenticator, Principal, sign_hs256_jwt


def test_api_lists_and_invokes_tools(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @scope("messages.send")
    def send_message(user_id: str, body: str) -> dict:
        return {"user_id": user_id, "body": body}

    client = TestClient(create_app(shield))

    tools = client.get("/tools")
    assert tools.status_code == 200
    assert tools.json()["tools"][0]["name"] == "send_message"

    denied = client.post(
        "/tools/send_message/invoke",
        json={"arguments": {"user_id": "u_1", "body": "hello"}, "actor": "agent"},
    )
    assert denied.status_code == 403
    assert denied.json()["status"] == "denied"

    invoked = client.post(
        "/tools/send_message/invoke",
        json={
            "arguments": {"user_id": "u_1", "body": "hello"},
            "actor": "agent",
            "scopes": ["messages.send"],
        },
    )
    assert invoked.status_code == 200
    assert invoked.json()["data"] == {"user_id": "u_1", "body": "hello"}

    audit = client.get("/audit")
    assert audit.status_code == 200
    assert len(audit.json()["events"]) == 2


def test_api_exports_mcp_style_tool_metadata(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    def get_status(service: str) -> dict:
        return {"service": service, "ok": True}

    client = TestClient(create_app(shield))
    response = client.get("/mcp/tools")
    assert response.status_code == 200
    tool = response.json()["tools"][0]
    assert tool["name"] == "get_status"
    assert "inputSchema" in tool
    assert "_toolrampart_approval_id" in tool["inputSchema"]["properties"]
    assert "_toolrampart_idempotency_key" in tool["inputSchema"]["properties"]


def test_api_uses_auth_principal_instead_of_request_body(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @scope("messages.send")
    def send_message(user_id: str, body: str) -> dict:
        return {"user_id": user_id, "body": body}

    client = TestClient(
        create_app(
            shield,
            authenticator=APIKeyAuthenticator(
                {"secret": Principal(actor="trusted-agent", scopes=["messages.send"])}
            ),
            require_auth=True,
        )
    )

    unauthorized = client.post(
        "/tools/send_message/invoke",
        json={
            "arguments": {"user_id": "u_1", "body": "hello"},
            "actor": "untrusted",
            "scopes": ["messages.send"],
        },
    )
    assert unauthorized.status_code == 401
    assert client.get("/audit").status_code == 401

    invoked = client.post(
        "/tools/send_message/invoke",
        headers={"Authorization": "Bearer secret"},
        json={
            "arguments": {"user_id": "u_1", "body": "hello"},
            "actor": "spoofed",
            "scopes": [],
        },
    )
    assert invoked.status_code == 200

    event = client.get("/audit", headers={"Authorization": "Bearer secret"}).json()["events"][0]
    assert event["actor"] == "trusted-agent"


def test_api_accepts_hashed_api_key_with_rotation(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @scope("billing.refund")
    def refund() -> dict:
        return {"ok": True}

    client = TestClient(
        create_app(
            shield,
            authenticator=HashedAPIKeyAuthenticator(
                {
                    "old": {
                        "actor": "old-agent",
                        "scopes": ["billing.*"],
                        "hash": hash_api_key("old-secret"),
                        "active": False,
                    },
                    "current": {
                        "actor": "rotated-agent",
                        "scopes": ["billing.*"],
                        "hash": hash_api_key("current-secret"),
                        "active": True,
                    },
                }
            ),
            require_auth=True,
        )
    )

    old_response = client.post(
        "/tools/refund/invoke",
        headers={"Authorization": "Bearer old-secret", "X-ToolRampart-Key-Id": "old"},
        json={},
    )
    assert old_response.status_code == 401

    response = client.post(
        "/tools/refund/invoke",
        headers={"Authorization": "Bearer current-secret", "X-ToolRampart-Key-Id": "current"},
        json={},
    )
    assert response.status_code == 200


def test_jwt_authenticator_accepts_signed_scopes(tmp_path):
    from toolrampart.auth import JWTAuthenticator

    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @scope("messages.send")
    def send_message(user_id: str) -> dict:
        return {"user_id": user_id}

    token = sign_hs256_jwt(
        {"sub": "jwt-agent", "scope": "messages.send", "exp": 4102444800},
        secret="test-secret",
    )
    client = TestClient(
        create_app(
            shield,
            authenticator=JWTAuthenticator(secret="test-secret"),
            require_auth=True,
        )
    )

    response = client.post(
        "/tools/send_message/invoke",
        headers={"Authorization": f"Bearer {token}"},
        json={"arguments": {"user_id": "u_1"}},
    )
    assert response.status_code == 200


def test_jwks_authenticator_accepts_rs256_token(tmp_path):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json_from_jwk(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "test-key"

    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @scope("messages.send")
    def send_message() -> dict:
        return {"ok": True}

    token = jwt.encode(
        {"sub": "jwks-agent", "scope": "messages.*", "exp": 4102444800},
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    client = TestClient(
        create_app(
            shield,
            authenticator=JWKSAuthenticator(jwks={"keys": [public_jwk]}),
            require_auth=True,
        )
    )

    response = client.post(
        "/tools/send_message/invoke",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert response.status_code == 200


def test_approval_endpoints_dashboard_and_metrics(tmp_path):
    from toolrampart import require_approval

    shield = ToolRampart(audit_path=tmp_path / "audit.db")

    @shield.tool
    @require_approval()
    def dangerous() -> dict:
        return {"ok": True}

    client = TestClient(create_app(shield))
    pending = client.post("/tools/dangerous/invoke", json={"actor": "agent"})
    approval_id = pending.json()["approval_id"]

    approvals = client.get("/approvals", params={"status": "pending"})
    assert approvals.status_code == 200
    assert approvals.json()["approvals"][0]["id"] == approval_id

    approved = client.post(
        f"/approvals/{approval_id}/approve",
        json={"actor": "lead", "note": "looks fine"},
    )
    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "approved"

    dashboard = client.get("/dashboard", params={"status": "all"})
    assert dashboard.status_code == 200
    assert "ToolRampart" in dashboard.text
    assert "data-action=\"approve\"" in dashboard.text

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "toolrampart_audit_events_total" in metrics.text


def test_api_accepts_idempotency_key_header(tmp_path):
    shield = ToolRampart(audit_path=tmp_path / "audit.db")
    calls = []

    @shield.tool
    def create_ticket(title: str) -> dict:
        calls.append(title)
        return {"ticket_id": f"t_{len(calls)}", "title": title}

    client = TestClient(create_app(shield))
    first = client.post(
        "/tools/create_ticket/invoke",
        headers={"Idempotency-Key": "ticket-1"},
        json={"arguments": {"title": "hello"}, "actor": "agent"},
    )
    second = client.post(
        "/tools/create_ticket/invoke",
        headers={"Idempotency-Key": "ticket-1"},
        json={"arguments": {"title": "hello"}, "actor": "agent"},
    )
    conflict = client.post(
        "/tools/create_ticket/invoke",
        headers={"Idempotency-Key": "ticket-1"},
        json={"arguments": {"title": "different"}, "actor": "agent"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["data"] == first.json()["data"]
    assert conflict.status_code == 409
    assert calls == ["hello"]


def json_from_jwk(value: str) -> dict:
    import json

    return json.loads(value)
