from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from .app import create_app
from .config import authenticator_from_config, load_config
from .core import ToolRampart, ToolContext, default_rampart
from .discovery import load_target
from .auth import generate_api_key, hash_api_key
from .storage import create_audit_store, create_rate_limit_store
from .telemetry import Telemetry

cli = typer.Typer(help="Expose Python functions as safe AI-agent tools.")
approvals_cli = typer.Typer(help="Review and resolve approval requests.")
auth_cli = typer.Typer(help="Manage ToolRampart auth helpers.")
migrations_cli = typer.Typer(help="Inspect local schema migrations.")
cli.add_typer(approvals_cli, name="approvals")
cli.add_typer(auth_cli, name="auth")
cli.add_typer(migrations_cli, name="migrations")


@cli.command("init")
def init_command(
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    config_path = Path("toolrampart.toml")
    tools_path = Path("tools.py")

    if force or not config_path.exists():
        config_path.write_text(_default_config(), encoding="utf-8")
        typer.echo("created toolrampart.toml")
    else:
        typer.echo("toolrampart.toml already exists")

    if force or not tools_path.exists():
        tools_path.write_text(_default_tools(), encoding="utf-8")
        typer.echo("created tools.py")
    else:
        typer.echo("tools.py already exists")


@cli.command("list")
def list_command(
    target: Annotated[
        str | None,
        typer.Argument(help="Module, package, or module:rampart target to import before listing."),
    ] = None,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
) -> None:
    shield = _load_runtime(target, config)
    payload = {"tools": [tool.public_schema() for tool in shield.list_tools()]}
    typer.echo(json.dumps(payload, indent=2, default=str))


@cli.command("call")
def call_command(
    name: Annotated[str, typer.Argument(help="Registered tool name.")],
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Module, package, or module:rampart target to import."),
    ] = None,
    args: Annotated[
        str,
        typer.Option("--args", "-a", help="JSON object of tool arguments."),
    ] = "{}",
    args_file: Annotated[
        Path | None,
        typer.Option("--args-file", help="Path to a JSON file containing tool arguments."),
    ] = None,
    actor: Annotated[str, typer.Option("--actor", help="Actor recorded in audit logs.")] = "cli",
    scope_values: Annotated[
        list[str] | None,
        typer.Option("--scope", help="Scope granted to this call."),
    ] = None,
    approved: Annotated[
        bool,
        typer.Option("--approved", help="Mark this call as externally approved."),
    ] = False,
    approval_id: Annotated[
        str | None,
        typer.Option("--approval-id", help="Approved request ID to attach to the call."),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        typer.Option("--idempotency-key", help="Deduplicate retries for this tool call."),
    ] = None,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
) -> None:
    shield = _load_runtime(target, config)
    arguments = _load_arguments(args, args_file)
    result = shield.invoke(
        name,
        arguments,
        ToolContext(
            actor=actor,
            scopes=scope_values or [],
            approved=approved,
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            source="cli",
        ),
    )
    typer.echo(result.model_dump_json(indent=2))


def _load_arguments(args: str, args_file: Path | None) -> dict[str, Any]:
    if args_file is not None:
        raw = args_file.read_text(encoding="utf-8-sig")
    elif args.startswith("@"):
        raw = Path(args[1:]).read_text(encoding="utf-8-sig")
    else:
        raw = args

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise typer.BadParameter("tool arguments must be a JSON object")
    return parsed


@cli.command("serve")
def serve_command(
    target: Annotated[
        str | None,
        typer.Argument(help="Module, package, or module:rampart target to import before serving."),
    ] = None,
    host: Annotated[str, typer.Option("--host", help="Host interface.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind.")] = 8000,
    reload: Annotated[
        bool,
        typer.Option("--reload", help="Enable uvicorn reload."),
    ] = False,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
) -> None:
    import uvicorn

    settings = load_config(config)
    shield = _load_runtime(target, config)
    api = create_app(
        shield,
        authenticator=authenticator_from_config(settings),
        require_auth=settings.auth.required,
        trust_headers=settings.auth.trust_headers,
    )
    uvicorn.run(api, host=host, port=port, reload=reload)


@cli.command("mcp")
def mcp_command(
    target: Annotated[
        str | None,
        typer.Argument(help="Module, package, or module:rampart target to import before serving MCP."),
    ] = None,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
    name: Annotated[str, typer.Option("--name", help="MCP server name.")] = "ToolRampart",
) -> None:
    from .mcp_server import run_stdio

    shield = _load_runtime(target, config)
    asyncio.run(run_stdio(shield, name=name))


@cli.command("audit")
def audit_command(
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Module, package, or module:rampart target to import."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Number of audit events.")] = 20,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
) -> None:
    shield = _load_runtime(target, config)
    typer.echo(json.dumps({"events": shield.audit_log.list_events(limit=limit)}, indent=2))


@cli.command("prune")
def prune_command(
    days: Annotated[int, typer.Option("--days", help="Keep this many days of audit logs.")] = 90,
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Module, package, or module:rampart target to import."),
    ] = None,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
) -> None:
    shield = _load_runtime(target, config)
    deleted = shield.prune_audit_logs(retention_days=days)
    typer.echo(json.dumps({"deleted": deleted}, indent=2))


@auth_cli.command("generate-key")
def auth_generate_key_command(
    prefix: Annotated[str, typer.Option("--prefix", help="API key prefix.")] = "trp",
) -> None:
    api_key = generate_api_key(prefix=prefix)
    typer.echo(api_key)


@auth_cli.command("hash-key")
def auth_hash_key_command(
    api_key: Annotated[str, typer.Argument(help="Plaintext API key to hash.")],
) -> None:
    typer.echo(hash_api_key(api_key))


@migrations_cli.command("status")
def migrations_status_command(
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Module, package, or module:rampart target to import."),
    ] = None,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
) -> None:
    shield = _load_runtime(target, config)
    migration_status = getattr(shield.audit_log, "migration_status", None)
    if not migration_status:
        typer.echo(json.dumps({"migrations": "not available for this storage adapter"}, indent=2))
        return
    typer.echo(json.dumps({"migrations": migration_status()}, indent=2))


@approvals_cli.command("list")
def approvals_list_command(
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Module, package, or module:rampart target to import."),
    ] = None,
    status: Annotated[str | None, typer.Option("--status", help="pending, approved, or rejected.")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Number of approval requests.")] = 20,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
) -> None:
    shield = _load_runtime(target, config)
    typer.echo(
        json.dumps(
            {"approvals": shield.list_approvals(status=status, limit=limit)},
            indent=2,
            default=str,
        )
    )


@approvals_cli.command("approve")
def approvals_approve_command(
    approval_id: Annotated[str, typer.Argument(help="Approval request ID.")],
    actor: Annotated[str, typer.Option("--actor", help="Approver identity.")] = "cli-approver",
    note: Annotated[str | None, typer.Option("--note", help="Resolution note.")] = None,
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Module, package, or module:rampart target to import."),
    ] = None,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
) -> None:
    shield = _load_runtime(target, config)
    typer.echo(json.dumps({"approval": shield.approve(approval_id, actor=actor, note=note)}, indent=2))


@approvals_cli.command("reject")
def approvals_reject_command(
    approval_id: Annotated[str, typer.Argument(help="Approval request ID.")],
    actor: Annotated[str, typer.Option("--actor", help="Approver identity.")] = "cli-approver",
    note: Annotated[str | None, typer.Option("--note", help="Resolution note.")] = None,
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Module, package, or module:rampart target to import."),
    ] = None,
    config: Annotated[str, typer.Option("--config", help="ToolRampart config path.")] = "toolrampart.toml",
) -> None:
    shield = _load_runtime(target, config)
    typer.echo(json.dumps({"approval": shield.reject(approval_id, actor=actor, note=note)}, indent=2))


def _load_runtime(target: str | None, config_path: str) -> ToolRampart:
    settings = load_config(config_path)
    try:
        shield = load_target(target)
    except TypeError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if shield is default_rampart:
        shield.execution_timeout_seconds = settings.execution.timeout_seconds
        shield.max_retries = settings.execution.max_retries
        shield.telemetry = Telemetry(
            enabled=settings.telemetry.enabled,
            service_name=settings.telemetry.service_name,
        )
        if settings.storage.storage_url and not settings.storage.storage_url.startswith("sqlite://"):
            shield._audit_log = create_audit_store(settings.storage.storage_url)  # noqa: SLF001
        else:
            shield._audit_log = None  # noqa: SLF001
            shield._audit_path = _sqlite_path(  # noqa: SLF001
                settings.storage.storage_url,
                settings.storage.audit_path,
            )
        shield._rate_limiter = create_rate_limit_store(settings.storage.redis_url)  # noqa: SLF001
    return shield


def _sqlite_path(storage_url: str | None, audit_path: str | None) -> str | None:
    if storage_url and storage_url.startswith("sqlite:///"):
        return storage_url.removeprefix("sqlite:///")
    return audit_path


def _default_config() -> str:
    return """# ToolRampart local configuration
[auth]
required = false
trust_headers = false

[auth.api_keys]
# "dev-secret" = { actor = "local-agent", scopes = ["billing.refund"] }

[auth.hashed_api_keys]
# "prod-key-2026-05" = { actor = "prod-agent", scopes = ["billing.*"], hash = "pbkdf2_sha256$...", active = true }

[execution]
timeout_seconds = 30
max_retries = 0

[storage]
audit_path = ".toolrampart/audit.db"
retention_days = 90
# storage_url = "postgresql://user:pass@localhost:5432/toolrampart"
# redis_url = "redis://localhost:6379/0"

[telemetry]
enabled = true
service_name = "toolrampart"
"""


def _default_tools() -> str:
    return '''from toolrampart import rate_limit, redact, require_approval, scope, side_effects, tool


@tool
@scope("billing.refund")
@require_approval(over_amount=500)
@redact(["email", "phone", "api_key"])
@rate_limit("10/hour/user")
@side_effects(idempotent=False, money_movement=True, writes_data=True)
def refund_user(user_id: str, amount: float, reason: str) -> dict:
    return {
        "status": "refund_started",
        "user_id": user_id,
        "amount": amount,
        "reason": reason,
    }
'''


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
