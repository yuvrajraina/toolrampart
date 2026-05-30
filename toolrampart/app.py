from __future__ import annotations

import html
import json
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .auth import Authenticator, Principal, principal_from_request
from .core import ToolRampart, ToolContext, default_rampart
from .mcp import export_tools
from ._version import __version__


class InvokeRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    actor: str = "anonymous"
    scopes: list[str] = Field(default_factory=list)
    approved: bool = False
    approved_by: str | None = None
    approval_id: str | None = None
    idempotency_key: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalResolutionRequest(BaseModel):
    actor: str = "approver"
    note: str | None = None


def create_app(
    shield: ToolRampart | None = None,
    *,
    authenticator: Authenticator | None = None,
    require_auth: bool = False,
    trust_headers: bool = False,
) -> FastAPI:
    current_shield = shield or default_rampart
    app = FastAPI(
        title="ToolRampart",
        summary="FastAPI for safe AI tools.",
        version=__version__,
    )
    app.state.toolrampart = current_shield

    async def principal_dependency(request: Request) -> Principal | None:
        return await principal_from_request(
            request,
            authenticator=authenticator,
            trust_headers=trust_headers,
            required=require_auth,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/tools")
    def list_tools(
        principal: Principal | None = Depends(principal_dependency),
    ) -> dict[str, list[dict[str, Any]]]:
        return {"tools": [tool.public_schema() for tool in current_shield.list_tools()]}

    @app.get("/mcp/tools")
    def list_mcp_tools(
        principal: Principal | None = Depends(principal_dependency),
    ) -> dict[str, list[dict[str, Any]]]:
        return export_tools(current_shield)

    @app.post("/tools/{tool_name}/invoke")
    async def invoke_tool(
        tool_name: str,
        raw_request: Request,
        request: InvokeRequest,
        principal: Principal | None = Depends(principal_dependency),
    ) -> JSONResponse:
        context = _context_from_request(request, principal, raw_request.headers)
        result = await current_shield.execute(tool_name, request.arguments, context)
        return JSONResponse(
            status_code=_status_code_for(result.status),
            content=jsonable_encoder(result.model_dump()),
        )

    @app.get("/audit")
    def audit_events(
        limit: int = Query(default=100, ge=1, le=500),
        principal: Principal | None = Depends(principal_dependency),
    ) -> dict[str, Any]:
        return {"events": current_shield.audit_log.list_events(limit=limit)}

    @app.get("/approvals")
    def list_approvals(
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        principal: Principal | None = Depends(principal_dependency),
    ) -> dict[str, Any]:
        return {
            "approvals": current_shield.list_approvals(status=status, limit=limit),
        }

    @app.post("/approvals/{approval_id}/approve")
    def approve_request(
        approval_id: str,
        resolution: ApprovalResolutionRequest,
        principal: Principal | None = Depends(principal_dependency),
    ) -> JSONResponse:
        actor = principal.actor if principal else resolution.actor
        approval = current_shield.approve(approval_id, actor=actor, note=resolution.note)
        return JSONResponse(
            status_code=200 if approval else 404,
            content={"approval": approval},
        )

    @app.post("/approvals/{approval_id}/reject")
    def reject_request(
        approval_id: str,
        resolution: ApprovalResolutionRequest,
        principal: Principal | None = Depends(principal_dependency),
    ) -> JSONResponse:
        actor = principal.actor if principal else resolution.actor
        approval = current_shield.reject(approval_id, actor=actor, note=resolution.note)
        return JSONResponse(
            status_code=200 if approval else 404,
            content={"approval": approval},
        )

    @app.get("/metrics")
    def metrics(
        principal: Principal | None = Depends(principal_dependency),
    ) -> PlainTextResponse:
        stats = current_shield.audit_log.stats()
        lines = [
            "# HELP toolrampart_audit_events_total Audit events by status.",
            "# TYPE toolrampart_audit_events_total counter",
        ]
        for status, count in stats["audit_events"].items():
            lines.append(f'toolrampart_audit_events_total{{status="{status}"}} {count}')
        lines.extend(
            [
                "# HELP toolrampart_approval_requests_total Approval requests by status.",
                "# TYPE toolrampart_approval_requests_total gauge",
            ]
        )
        for status, count in stats["approval_requests"].items():
            lines.append(f'toolrampart_approval_requests_total{{status="{status}"}} {count}')
        return PlainTextResponse("\n".join(lines) + "\n")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(
        status: str | None = Query(default="pending"),
        principal: Principal | None = Depends(principal_dependency),
    ) -> HTMLResponse:
        if status == "all":
            status = None
        return HTMLResponse(_dashboard_html(current_shield, approval_status=status))

    return app


def _context_from_request(
    request: InvokeRequest,
    principal: Principal | None,
    headers: dict[str, str] | Any,
) -> ToolContext:
    idempotency_key = (
        headers.get("Idempotency-Key")
        or headers.get("idempotency-key")
        or headers.get("X-Idempotency-Key")
        or headers.get("x-idempotency-key")
        or request.idempotency_key
    )
    if principal is not None:
        return ToolContext(
            actor=principal.actor,
            scopes=principal.scopes,
            approval_id=request.approval_id,
            idempotency_key=idempotency_key,
            request_id=request.request_id,
            source="rest",
            metadata={**principal.metadata, **request.metadata},
        )

    return ToolContext(
        actor=request.actor,
        scopes=request.scopes,
        approved=request.approved,
        approved_by=request.approved_by,
        approval_id=request.approval_id,
        idempotency_key=idempotency_key,
        request_id=request.request_id,
        source="rest",
        metadata=request.metadata,
    )


def _dashboard_html(shield: ToolRampart, *, approval_status: str | None = "pending") -> str:
    tools = shield.list_tools()
    approvals = shield.list_approvals(status=approval_status, limit=25)
    events = shield.audit_log.list_events(limit=25)

    tool_rows = "".join(
        "<tr>"
        f"<td>{html.escape(tool.name)}</td>"
        f"<td>{html.escape(tool.description)}</td>"
        f"<td><code>{html.escape(json.dumps(tool.side_effects.as_dict()))}</code></td>"
        f"<td><code>{html.escape(json.dumps(tool.public_schema()['policies']))}</code></td>"
        "</tr>"
        for tool in tools
    )
    approval_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(item['id'])}</code></td>"
        f"<td>{html.escape(item['tool_name'])}</td>"
        f"<td>{html.escape(item['actor'])}</td>"
        f"<td>{html.escape(item['status'])}</td>"
        f"<td>{html.escape(item['reason'])}</td>"
        f"<td><code>{html.escape(item['arguments_hash'])}</code></td>"
        f"<td><code>{html.escape(json.dumps(item['arguments']))}</code></td>"
        "<td>"
        f"<button data-action=\"approve\" data-id=\"{html.escape(item['id'])}\""
        f" {'disabled' if item['status'] != 'pending' else ''}>Approve</button> "
        f"<button data-action=\"reject\" data-id=\"{html.escape(item['id'])}\""
        f" {'disabled' if item['status'] != 'pending' else ''}>Reject</button>"
        "</td>"
        "</tr>"
        for item in approvals
    )
    if not approval_rows:
        approval_rows = "<tr><td colspan=\"8\">No approval requests found.</td></tr>"
    event_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['status'])}</td>"
        f"<td>{html.escape(item['tool_name'])}</td>"
        f"<td>{html.escape(item['actor'])}</td>"
        f"<td><code>{html.escape(item['id'])}</code></td>"
        "</tr>"
        for item in events
    )
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ToolRampart Dashboard</title>
  <style>
    body {{ margin: 0; font-family: Inter, system-ui, sans-serif; background: #f6f8fa; color: #1f2328; }}
    header {{ padding: 24px 32px; background: #111827; color: white; }}
    main {{ padding: 24px 32px; display: grid; gap: 24px; }}
    section {{ background: white; border: 1px solid #d8dee4; border-radius: 8px; overflow: hidden; }}
    h1, h2 {{ margin: 0; }}
    h2 {{ padding: 16px 18px; font-size: 18px; border-bottom: 1px solid #d8dee4; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #d8dee4; text-align: left; vertical-align: top; }}
    th {{ background: #f6f8fa; font-weight: 700; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }}
    nav {{ display: flex; gap: 8px; padding: 12px 18px; border-bottom: 1px solid #d8dee4; }}
    a, button {{ border: 1px solid #8c959f; border-radius: 6px; background: white; color: #1f2328; padding: 6px 10px; text-decoration: none; cursor: pointer; }}
    button:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    .status {{ padding: 8px 18px; color: #57606a; min-height: 20px; }}
  </style>
</head>
<body>
  <header>
    <h1>ToolRampart</h1>
    <p>Safe tool execution, approvals, audit, and policy state.</p>
  </header>
  <main>
    <section>
      <h2>Tools</h2>
      <table><thead><tr><th>Name</th><th>Description</th><th>Side Effects</th><th>Policies</th></tr></thead><tbody>{tool_rows}</tbody></table>
    </section>
    <section>
      <h2>Approvals</h2>
      <nav>
        <a href="/dashboard?status=pending">Pending</a>
        <a href="/dashboard?status=approved">Approved</a>
        <a href="/dashboard?status=rejected">Rejected</a>
        <a href="/dashboard?status=all">All</a>
      </nav>
      <div class="status" id="approval-status"></div>
      <table><thead><tr><th>ID</th><th>Tool</th><th>Actor</th><th>Status</th><th>Reason</th><th>Argument Hash</th><th>Arguments</th><th>Action</th></tr></thead><tbody>{approval_rows}</tbody></table>
    </section>
    <section>
      <h2>Recent Audit Events</h2>
      <table><thead><tr><th>Status</th><th>Tool</th><th>Actor</th><th>Audit ID</th></tr></thead><tbody>{event_rows}</tbody></table>
    </section>
  </main>
  <script>
    const status = document.getElementById("approval-status");
    document.querySelectorAll("button[data-action]").forEach((button) => {{
      button.addEventListener("click", async () => {{
        const action = button.dataset.action;
        const approvalId = button.dataset.id;
        const response = await fetch(`/approvals/${{approvalId}}/${{action}}`, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ actor: "dashboard" }})
        }});
        if (response.ok) {{
          status.textContent = `${{action}}d approval ${{approvalId}}`;
          window.setTimeout(() => window.location.reload(), 500);
        }} else {{
          status.textContent = `Failed to ${{action}} approval ${{approvalId}}`;
        }}
      }});
    }});
  </script>
</body>
</html>
"""


def _status_code_for(status: str) -> int:
    return {
        "success": 200,
        "validation_error": 422,
        "denied": 403,
        "requires_approval": 202,
        "rejected": 403,
        "rate_limited": 429,
        "idempotency_conflict": 409,
        "timeout": 504,
        "error": 500,
    }.get(status, 500)


app = create_app()
