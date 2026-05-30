from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, create_model

from .audit import AuditLog, hash_arguments
from .exceptions import SubprocessExecutionError, SubprocessTimeoutError, ToolNotFoundError, ToolRegistrationError
from .isolation import run_in_subprocess
from .policies import (
    ApprovalPolicy,
    PolicyCallable,
    PolicyRule,
    RateLimitRule,
    SideEffectMetadata,
    parse_rate_limit,
    redact_data,
)
from .storage import AuditStore, RateLimitStore
from .telemetry import Telemetry

logger = logging.getLogger("toolrampart")


class ToolContext(BaseModel):
    actor: str = "anonymous"
    scopes: list[str] = Field(default_factory=list)
    approved: bool = False
    approved_by: str | None = None
    approval_id: str | None = None
    idempotency_key: str | None = None
    idempotency_started: bool = False
    request_id: str | None = None
    source: str = "python"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    status: Literal[
        "success",
        "validation_error",
        "denied",
        "requires_approval",
        "rejected",
        "rate_limited",
        "idempotency_conflict",
        "timeout",
        "error",
    ]
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


@dataclass
class ToolMetadata:
    required_scope: str | None = None
    approval_policy: ApprovalPolicy | None = None
    redact_fields: set[str] = field(default_factory=set)
    rate_limit_rule: RateLimitRule | None = None
    policy_rules: list[PolicyRule] = field(default_factory=list)
    side_effects: SideEffectMetadata = field(default_factory=SideEffectMetadata)
    timeout_seconds: float | None = None
    max_retries: int | None = None
    execution_mode: Literal["thread", "subprocess"] = "thread"


@dataclass
class ToolDefinition:
    name: str
    func: Callable[..., Any]
    description: str
    input_model: type[BaseModel]
    output_adapter: TypeAdapter[Any] | None = None
    output_schema: dict[str, Any] | None = None
    required_scope: str | None = None
    approval_policy: ApprovalPolicy | None = None
    redact_fields: set[str] = field(default_factory=set)
    rate_limit_rule: RateLimitRule | None = None
    policy_rules: list[PolicyRule] = field(default_factory=list)
    side_effects: SideEffectMetadata = field(default_factory=SideEffectMetadata)
    timeout_seconds: float | None = None
    max_retries: int | None = None
    execution_mode: Literal["thread", "subprocess"] = "thread"

    @classmethod
    def from_function(
        cls,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        side_effects: SideEffectMetadata | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        execution_mode: Literal["thread", "subprocess"] | None = None,
    ) -> "ToolDefinition":
        tool_name = name or func.__name__
        metadata = _metadata_for(func)
        input_model = _model_from_signature(tool_name, func)
        output_adapter, output_schema = _output_adapter_from_signature(func)
        tool_description = description or _description_for(func)
        return cls(
            name=tool_name,
            func=func,
            description=tool_description,
            input_model=input_model,
            output_adapter=output_adapter,
            output_schema=output_schema,
            required_scope=metadata.required_scope,
            approval_policy=metadata.approval_policy,
            redact_fields=set(metadata.redact_fields),
            rate_limit_rule=metadata.rate_limit_rule,
            policy_rules=list(metadata.policy_rules),
            side_effects=side_effects or metadata.side_effects,
            timeout_seconds=timeout_seconds if timeout_seconds is not None else metadata.timeout_seconds,
            max_retries=max_retries if max_retries is not None else metadata.max_retries,
            execution_mode=execution_mode or metadata.execution_mode,
        )

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        model = self.input_model.model_validate(arguments)
        return model.model_dump()

    async def call(self, arguments: dict[str, Any]) -> Any:
        if inspect.iscoroutinefunction(self.func):
            result = await self.func(**arguments)
        else:
            result = await asyncio.to_thread(self.func, **arguments)
        if inspect.isawaitable(result):
            return await result
        return result

    def validate_result(self, result: Any) -> Any:
        if not self.output_adapter:
            return result
        return self.output_adapter.validate_python(result)

    def public_schema(self) -> dict[str, Any]:
        policy: dict[str, Any] = {}
        if self.required_scope:
            policy["scope"] = self.required_scope
        if self.approval_policy:
            policy["approval"] = {
                "conditions": self.approval_policy.conditions,
                "always": self.approval_policy.always,
            }
        if self.rate_limit_rule:
            policy["rate_limit"] = self.rate_limit_rule.expression
        if self.redact_fields:
            policy["redacts"] = sorted(self.redact_fields)
        if self.policy_rules:
            policy["custom"] = [
                {"name": rule.name, "description": rule.description}
                for rule in self.policy_rules
            ]
        if self.timeout_seconds is not None:
            policy["timeout_seconds"] = self.timeout_seconds
        if self.max_retries is not None:
            policy["max_retries"] = self.max_retries
        policy["execution_mode"] = self.execution_mode

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_schema,
            "side_effects": self.side_effects.as_dict(),
            "policies": policy,
        }


class ToolRampart:
    def __init__(
        self,
        *,
        audit_path: str | Path | None = None,
        audit_log: AuditStore | None = None,
        rate_limiter: RateLimitStore | None = None,
        execution_timeout_seconds: float | None = 30,
        max_retries: int = 0,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._audit_path = audit_path
        self._audit_log: AuditStore | None = audit_log
        self._rate_limiter = rate_limiter
        self.execution_timeout_seconds = execution_timeout_seconds
        self.max_retries = max_retries
        self.telemetry = telemetry or Telemetry()
        self._tools: dict[str, ToolDefinition] = {}

    @property
    def audit_log(self) -> AuditStore:
        if self._audit_log is None:
            self._audit_log = AuditLog(self._audit_path)
        return self._audit_log

    @property
    def rate_limiter(self) -> RateLimitStore:
        return self._rate_limiter or self.audit_log

    def tool(
        self,
        func: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        side_effects: SideEffectMetadata | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        execution_mode: Literal["thread", "subprocess"] | None = None,
    ) -> Callable[..., Any]:
        def decorator(inner: Callable[..., Any]) -> Callable[..., Any]:
            self.register(
                ToolDefinition.from_function(
                    inner,
                    name=name,
                    description=description,
                    side_effects=side_effects,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                    execution_mode=execution_mode,
                )
            )
            return inner

        if func is not None:
            return decorator(func)
        return decorator

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ToolRegistrationError(f"tool '{definition.name}' is already registered")
        self._tools[definition.name] = definition

    def get_tool(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"tool '{name}' is not registered") from exc

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def list_approvals(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.audit_log.list_approval_requests(status=status, limit=limit)

    def approve(self, approval_id: str, *, actor: str, note: str | None = None) -> dict[str, Any] | None:
        return self.audit_log.resolve_approval_request(
            approval_id=approval_id,
            status="approved",
            resolved_by=actor,
            note=note,
        )

    def reject(self, approval_id: str, *, actor: str, note: str | None = None) -> dict[str, Any] | None:
        return self.audit_log.resolve_approval_request(
            approval_id=approval_id,
            status="rejected",
            resolved_by=actor,
            note=note,
        )

    def prune_audit_logs(self, *, retention_days: int) -> int:
        before = time.time() - retention_days * 24 * 60 * 60
        return self.audit_log.prune_events(before=before)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        context: ToolContext | dict[str, Any] | None = None,
    ) -> ToolResult:
        tool_definition = self.get_tool(name)
        raw_arguments = arguments or {}
        tool_context = _coerce_context(context)
        tool_context.idempotency_started = False
        started_at = time.time()
        with self.telemetry.start_tool_span(
            tool_name=tool_definition.name,
            actor=tool_context.actor,
            source=tool_context.source,
        ):
            try:
                validated_arguments = tool_definition.validate_arguments(raw_arguments)
                self.telemetry.checkpoint("validated", {"toolrampart.tool.name": tool_definition.name})
            except ValidationError as exc:
                return self._finish(
                    tool=tool_definition,
                    context=tool_context,
                    started_at=started_at,
                    status="validation_error",
                    arguments=raw_arguments,
                    error=str(exc),
                    error_type="InputValidationError",
                    message="tool arguments failed validation",
                )

            scope_result = self._check_scope(tool_definition, tool_context)
            if scope_result:
                return self._finish(
                    tool=tool_definition,
                    context=tool_context,
                    started_at=started_at,
                    status="denied",
                    arguments=validated_arguments,
                    error=scope_result,
                    error_type="ScopeDenied",
                    message=scope_result,
                )

            policy_result = await self._check_policies(tool_definition, tool_context, validated_arguments)
            if policy_result:
                return self._finish(
                    tool=tool_definition,
                    context=tool_context,
                    started_at=started_at,
                    status="denied",
                    arguments=validated_arguments,
                    error=policy_result,
                    error_type="PolicyDenied",
                    message=policy_result,
                )

            approval_reason = self._check_approval(tool_definition, validated_arguments)
            if approval_reason:
                approval_result = self._resolve_approval_gate(
                    tool_definition,
                    tool_context,
                    validated_arguments,
                    approval_reason,
                )
                if approval_result is not None:
                    status, message, approval_id, approved_by = approval_result
                    if status == "approved":
                        tool_context.approved = True
                        tool_context.approved_by = approved_by
                        tool_context.approval_id = approval_id
                        self.telemetry.checkpoint("approval.accepted")
                    else:
                        return self._finish(
                            tool=tool_definition,
                            context=tool_context,
                            started_at=started_at,
                            status=status,
                            arguments=validated_arguments,
                            error=message,
                            error_type=_approval_error_type(status),
                            approval_required=status == "requires_approval",
                            approval_id=approval_id,
                            message=message,
                        )

            idempotency_result = self._check_idempotency(tool_definition, tool_context, validated_arguments, started_at)
            if idempotency_result is not None:
                return idempotency_result

            rate_limit_message = self._check_rate_limit(tool_definition, tool_context)
            if rate_limit_message:
                return self._finish(
                    tool=tool_definition,
                    context=tool_context,
                    started_at=started_at,
                    status="rate_limited",
                    arguments=validated_arguments,
                    error=rate_limit_message,
                    error_type="RateLimited",
                    message=rate_limit_message,
                )

            return await self._execute_tool(
                tool=tool_definition,
                context=tool_context,
                arguments=validated_arguments,
                started_at=started_at,
            )

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        context: ToolContext | dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute(name, arguments, context))
        raise RuntimeError("use 'await rampart.execute(...)' inside a running event loop")

    def _check_scope(self, tool_definition: ToolDefinition, context: ToolContext) -> str | None:
        if not tool_definition.required_scope:
            return None
        if _scope_grants(tool_definition.required_scope, context.scopes):
            return None
        return f"missing required scope: {tool_definition.required_scope}"

    async def _check_policies(
        self,
        tool_definition: ToolDefinition,
        context: ToolContext,
        arguments: dict[str, Any],
    ) -> str | None:
        for rule in tool_definition.policy_rules:
            denial = await rule.evaluate(context, arguments)
            if denial:
                return denial
        return None

    def _check_approval(
        self,
        tool_definition: ToolDefinition,
        arguments: dict[str, Any],
    ) -> str | None:
        if not tool_definition.approval_policy:
            return None
        return tool_definition.approval_policy.required_reason(arguments)

    def _resolve_approval_gate(
        self,
        tool_definition: ToolDefinition,
        context: ToolContext,
        arguments: dict[str, Any],
        reason: str,
    ) -> tuple[str, str, str | None, str | None] | None:
        if context.approved:
            return None

        if context.approval_id:
            approval = self.audit_log.get_approval_request(context.approval_id)
            if approval is None:
                return ("requires_approval", "approval request was not found", context.approval_id, None)
            if approval["tool_name"] != tool_definition.name:
                return ("denied", "approval request belongs to a different tool", context.approval_id, None)
            if approval["arguments_hash"] != hash_arguments(arguments):
                return ("denied", "approval request does not match these arguments", context.approval_id, None)
            if approval["status"] == "approved":
                return ("approved", "approval accepted", context.approval_id, approval["resolved_by"])
            if approval["status"] == "rejected":
                return ("rejected", "approval request was rejected", context.approval_id, approval["resolved_by"])
            return ("requires_approval", reason, context.approval_id, None)

        redacted_arguments = redact_data(arguments, tool_definition.redact_fields)
        approval_id = self.audit_log.create_approval_request(
            tool_name=tool_definition.name,
            actor=context.actor,
            reason=reason,
            arguments=redacted_arguments,
            raw_arguments=arguments,
            metadata={
                "request_id": context.request_id,
                "source": context.source,
                **context.metadata,
            },
        )
        return ("requires_approval", reason, approval_id, None)

    def _check_rate_limit(
        self,
        tool_definition: ToolDefinition,
        context: ToolContext,
    ) -> str | None:
        rule = tool_definition.rate_limit_rule
        if not rule:
            return None

        bucket = rule.bucket_for(tool_name=tool_definition.name, actor=context.actor)
        since = time.time() - rule.window_seconds
        used = self.rate_limiter.count_rate_events(
            tool_name=tool_definition.name,
            bucket=bucket,
            since=since,
        )
        if used >= rule.limit:
            return f"rate limit exceeded: {rule.expression}"

        self.rate_limiter.record_rate_event(tool_name=tool_definition.name, bucket=bucket)
        return None

    def _check_idempotency(
        self,
        tool_definition: ToolDefinition,
        context: ToolContext,
        arguments: dict[str, Any],
        started_at: float,
    ) -> ToolResult | None:
        if not context.idempotency_key:
            return None

        state = self.audit_log.start_idempotency_record(
            tool_name=tool_definition.name,
            actor=context.actor,
            key=context.idempotency_key,
            arguments=arguments,
        )
        record = state["record"]
        if state["state"] == "started":
            context.idempotency_started = True
            self.telemetry.checkpoint("idempotency.started")
            return None
        if state["state"] == "replay":
            self.telemetry.checkpoint("idempotency.replay")
            result = ToolResult.model_validate(record["result"]).model_copy(update={"replayed": True})
            self.telemetry.record_result(
                tool_name=tool_definition.name,
                status=result.status,
                duration_seconds=max(0.0, time.time() - started_at),
                error_type=result.error_type,
                replayed=True,
            )
            return result
        if state["state"] == "in_progress":
            return self._finish(
                tool=tool_definition,
                context=context,
                started_at=started_at,
                status="idempotency_conflict",
                arguments=arguments,
                error="idempotency key is already in progress",
                error_type="IdempotencyInProgress",
                message="idempotency key is already in progress",
            )
        return self._finish(
            tool=tool_definition,
            context=context,
            started_at=started_at,
            status="idempotency_conflict",
            arguments=arguments,
            error="idempotency key was already used with different arguments",
            error_type="IdempotencyConflict",
            message="idempotency key was already used with different arguments",
        )

    async def _execute_tool(
        self,
        *,
        tool: ToolDefinition,
        context: ToolContext,
        arguments: dict[str, Any],
        started_at: float,
    ) -> ToolResult:
        timeout_seconds = (
            tool.timeout_seconds
            if tool.timeout_seconds is not None
            else self.execution_timeout_seconds
        )
        max_retries = tool.max_retries if tool.max_retries is not None else self.max_retries
        attempts = max(0, max_retries) + 1
        last_error: BaseException | None = None

        for attempt in range(1, attempts + 1):
            try:
                data = await self._call_tool_with_mode(tool, arguments, timeout_seconds)
                data = tool.validate_result(data)
                logger.info("tool execution succeeded", extra={"tool": tool.name, "attempt": attempt})
                return self._finish(
                    tool=tool,
                    context=context,
                    started_at=started_at,
                    status="success",
                    arguments=arguments,
                    data=_json_safe(data),
                    attempts=attempt,
                )
            except asyncio.TimeoutError as exc:
                last_error = exc
                logger.warning("tool execution timed out", extra={"tool": tool.name, "attempt": attempt})
                if attempt >= attempts:
                    return self._finish(
                        tool=tool,
                        context=context,
                        started_at=started_at,
                        status="timeout",
                        arguments=arguments,
                        error=f"tool timed out after {timeout_seconds} seconds",
                        error_type="TimeoutError",
                        message="tool execution timed out",
                        attempts=attempt,
                    )
            except ValidationError as exc:
                logger.warning("tool output validation failed", extra={"tool": tool.name, "attempt": attempt})
                return self._finish(
                    tool=tool,
                    context=context,
                    started_at=started_at,
                    status="error",
                    arguments=arguments,
                    error=str(exc),
                    error_type="OutputValidationError",
                    message="tool result failed output validation",
                    attempts=attempt,
                )
            except Exception as exc:  # pragma: no cover - traceback belongs to caller logs
                last_error = exc
                logger.warning("tool execution failed", extra={"tool": tool.name, "attempt": attempt})
                if attempt >= attempts:
                    return self._finish(
                        tool=tool,
                        context=context,
                        started_at=started_at,
                        status="error",
                        arguments=arguments,
                        error=f"{type(exc).__name__}: {exc}",
                        error_type=type(exc).__name__,
                        message="tool execution failed",
                        attempts=attempt,
                    )

        return self._finish(
            tool=tool,
            context=context,
            started_at=started_at,
            status="error",
            arguments=arguments,
            error=f"{type(last_error).__name__}: {last_error}",
            error_type=type(last_error).__name__ if last_error else "ExecutionError",
            message="tool execution failed",
            attempts=attempts,
        )

    async def _call_tool_with_mode(
        self,
        tool: ToolDefinition,
        arguments: dict[str, Any],
        timeout_seconds: float | None,
    ) -> Any:
        if tool.execution_mode == "subprocess":
            try:
                return await asyncio.to_thread(
                    run_in_subprocess,
                    tool.func,
                    arguments,
                    timeout_seconds=timeout_seconds,
                )
            except SubprocessTimeoutError as exc:
                raise asyncio.TimeoutError(str(exc)) from exc
        call = tool.call(arguments)
        return (
            await asyncio.wait_for(call, timeout=timeout_seconds)
            if timeout_seconds is not None
            else await call
        )

    def _complete_idempotency_if_needed(
        self,
        tool: ToolDefinition,
        context: ToolContext,
        result: ToolResult,
    ) -> None:
        if not context.idempotency_key or not context.idempotency_started:
            return
        self.audit_log.complete_idempotency_record(
            tool_name=tool.name,
            actor=context.actor,
            key=context.idempotency_key,
            result=result.model_dump(),
        )

    def _finish(
        self,
        *,
        tool: ToolDefinition,
        context: ToolContext,
        started_at: float,
        status: str,
        arguments: dict[str, Any],
        data: Any = None,
        error: str | None = None,
        error_type: str | None = None,
        approval_required: bool = False,
        approval_id: str | None = None,
        message: str | None = None,
        attempts: int = 0,
    ) -> ToolResult:
        redacted_arguments = redact_data(arguments, tool.redact_fields)
        redacted_data = redact_data(data, tool.redact_fields)
        audit_id = self.audit_log.log_event(
            tool_name=tool.name,
            actor=context.actor,
            status=status,
            arguments=redacted_arguments,
            result=redacted_data,
            error=error,
            started_at=started_at,
            metadata={
                "request_id": context.request_id,
                "approval_id": approval_id or context.approval_id,
                "approved_by": context.approved_by,
                "source": context.source,
                "attempts": attempts,
                **context.metadata,
            },
        )
        result = ToolResult(
            status=status,
            tool_name=tool.name,
            data=data,
            error=error,
            error_type=error_type,
            audit_id=audit_id,
            approval_required=approval_required,
            approval_id=approval_id or context.approval_id,
            message=message,
            attempts=attempts,
        )
        self._complete_idempotency_if_needed(tool, context, result)
        self.telemetry.record_result(
            tool_name=tool.name,
            status=status,
            duration_seconds=max(0.0, time.time() - started_at),
            error_type=error_type,
        )
        return result


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    side_effects: SideEffectMetadata | None = None,
    timeout_seconds: float | None = None,
    max_retries: int | None = None,
    execution_mode: Literal["thread", "subprocess"] | None = None,
) -> Callable[..., Any]:
    return default_rampart.tool(
        func,
        name=name,
        description=description,
        side_effects=side_effects,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        execution_mode=execution_mode,
    )


def scope(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _metadata_for(func).required_scope = name
        return func

    return decorator


def require_approval(
    func: Callable[..., Any] | None = None,
    **conditions: Any,
) -> Callable[..., Any]:
    def decorator(inner: Callable[..., Any]) -> Callable[..., Any]:
        _metadata_for(inner).approval_policy = ApprovalPolicy(
            conditions=conditions,
            always=not bool(conditions),
        )
        return inner

    if func is not None:
        return decorator(func)
    return decorator


def redact(fields: list[str] | tuple[str, ...] | set[str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _metadata_for(func).redact_fields.update(fields)
        return func

    return decorator


def rate_limit(expression: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    rule = parse_rate_limit(expression)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _metadata_for(func).rate_limit_rule = rule
        return func

    return decorator


def policy(
    check: PolicyCallable,
    *,
    name: str | None = None,
    description: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    rule = PolicyRule(
        check=check,
        name=name or getattr(check, "__name__", "policy"),
        description=description,
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _metadata_for(func).policy_rules.append(rule)
        return func

    return decorator


def timeout(seconds: float | None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _metadata_for(func).timeout_seconds = seconds
        return func

    return decorator


def max_retries(count: int) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if count < 0:
            raise ValueError("max retries cannot be negative")
        _metadata_for(func).max_retries = count
        return func

    return decorator


def side_effects(
    *,
    read_only: bool = False,
    idempotent: bool = False,
    destructive: bool = False,
    external_network: bool = False,
    money_movement: bool = False,
    writes_data: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    metadata = SideEffectMetadata(
        read_only=read_only,
        idempotent=idempotent,
        destructive=destructive,
        external_network=external_network,
        money_movement=money_movement,
        writes_data=writes_data,
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _metadata_for(func).side_effects = metadata
        return func

    return decorator


def isolated_process(
    func: Callable[..., Any] | None = None,
) -> Callable[..., Any]:
    def decorator(inner: Callable[..., Any]) -> Callable[..., Any]:
        _metadata_for(inner).execution_mode = "subprocess"
        return inner

    if func is not None:
        return decorator(func)
    return decorator


def _metadata_for(func: Callable[..., Any]) -> ToolMetadata:
    metadata = getattr(func, "__toolrampart_metadata__", None)
    if metadata is None:
        metadata = ToolMetadata()
        setattr(func, "__toolrampart_metadata__", metadata)
    return metadata


def _description_for(func: Callable[..., Any]) -> str:
    doc = inspect.getdoc(func)
    if not doc:
        return ""
    return doc.splitlines()[0]


def _model_from_signature(name: str, func: Callable[..., Any]) -> type[BaseModel]:
    signature = inspect.signature(func)
    fields: dict[str, tuple[Any, Any]] = {}

    for parameter in signature.parameters.values():
        if parameter.kind in {
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        }:
            raise ToolRegistrationError(
                f"tool '{name}' cannot use *args or **kwargs parameters"
            )

        annotation = parameter.annotation
        if annotation is inspect.Parameter.empty:
            annotation = Any

        default = parameter.default
        if default is inspect.Parameter.empty:
            default = ...

        fields[parameter.name] = (annotation, default)

    return create_model(
        f"{name.title().replace('_', '')}Input",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _output_adapter_from_signature(func: Callable[..., Any]) -> tuple[TypeAdapter[Any] | None, dict[str, Any] | None]:
    annotation = inspect.signature(func).return_annotation
    if annotation is inspect.Signature.empty or annotation is Any:
        return None, None
    adapter = TypeAdapter(annotation)
    try:
        schema = adapter.json_schema()
    except Exception:
        schema = None
    return adapter, schema


def _coerce_context(context: ToolContext | dict[str, Any] | None) -> ToolContext:
    if context is None:
        return ToolContext()
    if isinstance(context, ToolContext):
        return context
    return ToolContext.model_validate(context)


def _approval_error_type(status: str) -> str:
    if status == "requires_approval":
        return "ApprovalRequired"
    if status == "rejected":
        return "ApprovalRejected"
    return "ApprovalDenied"


def _scope_grants(required: str, granted_scopes: list[str]) -> bool:
    for granted in granted_scopes:
        if granted == "*" or granted == required:
            return True
        if granted.endswith(".*"):
            prefix = granted[:-2]
            if required == prefix or required.startswith(prefix + "."):
                return True
    return False


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


default_rampart = ToolRampart()
