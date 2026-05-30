from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field


class ToolRampartClientError(Exception):
    """Base exception for ToolRampart client failures."""


class ToolRampartHTTPError(ToolRampartClientError):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"ToolRampart request failed: HTTP {response.status_code}")


class ClientToolResult(BaseModel):
    status: str
    tool_name: str
    data: Any = None
    error: str | None = None
    error_type: str | None = None
    audit_id: str | None = None
    approval_required: bool = False
    approval_id: str | None = None
    message: str | None = None
    attempts: int = 0
    replayed: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "success"


class InvokeOptions(BaseModel):
    actor: str = "client"
    scopes: list[str] = Field(default_factory=list)
    approved: bool = False
    approved_by: str | None = None
    approval_id: str | None = None
    idempotency_key: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolRampartClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        bearer_token: str | None = None,
        timeout: float = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._default_headers: dict[str, str] = {}
        token = bearer_token or api_key
        if token:
            self._default_headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "ToolRampartClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def health(self) -> dict[str, Any]:
        return self._get_json("/health")

    def tools(self) -> list[dict[str, Any]]:
        return self._get_json("/tools")["tools"]

    def mcp_tools(self) -> list[dict[str, Any]]:
        return self._get_json("/mcp/tools")["tools"]

    def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        actor: str = "client",
        scopes: list[str] | None = None,
        approved: bool = False,
        approved_by: str | None = None,
        approval_id: str | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ClientToolResult:
        options = InvokeOptions(
            actor=actor,
            scopes=scopes or [],
            approved=approved,
            approved_by=approved_by,
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            request_id=request_id,
            metadata=metadata or {},
        )
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        payload = {
            "arguments": arguments or {},
            **options.model_dump(exclude_none=True),
        }
        response = self._request(
            "POST",
            f"/tools/{tool_name}/invoke",
            json=payload,
            headers=headers,
            raise_for_status=False,
        )
        return ClientToolResult.model_validate(response.json())

    def approvals(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        return self._get_json("/approvals", params=params)["approvals"]

    def approve(
        self,
        approval_id: str,
        *,
        actor: str = "client",
        note: str | None = None,
    ) -> dict[str, Any] | None:
        return self._post_json(
            f"/approvals/{approval_id}/approve",
            json={"actor": actor, "note": note},
        )["approval"]

    def reject(
        self,
        approval_id: str,
        *,
        actor: str = "client",
        note: str | None = None,
    ) -> dict[str, Any] | None:
        return self._post_json(
            f"/approvals/{approval_id}/reject",
            json={"actor": actor, "note": note},
        )["approval"]

    def audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._get_json("/audit", params={"limit": limit})["events"]

    def metrics(self) -> str:
        response = self._request("GET", "/metrics")
        return response.text

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", path, params=params).json()

    def _post_json(self, path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, json=json).json()

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        raise_for_status: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        merged_headers = {**self._default_headers, **(headers or {})}
        response = self._client.request(
            method,
            f"{self.base_url}{path}",
            headers=merged_headers,
            **kwargs,
        )
        if raise_for_status and response.status_code >= 400:
            raise ToolRampartHTTPError(response)
        return response
