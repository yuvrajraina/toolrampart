from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .exceptions import ToolRampartError


class PolicyDenied(ToolRampartError):
    """Raised internally when a custom policy denies execution."""


@dataclass(frozen=True)
class ApprovalPolicy:
    conditions: dict[str, Any] = field(default_factory=dict)
    always: bool = False

    def required_reason(self, arguments: dict[str, Any]) -> str | None:
        if self.always:
            return "approval is required"

        reasons: list[str] = []
        for condition, threshold in self.conditions.items():
            if condition.startswith("over_"):
                field_name = condition.removeprefix("over_")
                value = arguments.get(field_name)
                if value is not None and _is_over(value, threshold):
                    reasons.append(f"{field_name} exceeds {threshold}")
            elif condition.startswith("at_or_over_"):
                field_name = condition.removeprefix("at_or_over_")
                value = arguments.get(field_name)
                if value is not None and _is_at_or_over(value, threshold):
                    reasons.append(f"{field_name} is at least {threshold}")
            elif arguments.get(condition) == threshold:
                reasons.append(f"{condition} matched {threshold!r}")

        if not reasons:
            return None
        return "; ".join(reasons)


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int
    per: str
    expression: str

    def bucket_for(self, *, tool_name: str, actor: str) -> str:
        if self.per in {"user", "actor"}:
            return f"user:{actor or 'anonymous'}"
        if self.per == "global":
            return "global"
        if self.per == "tool":
            return f"tool:{tool_name}"
        return f"{self.per}:{actor or 'anonymous'}"


PolicyCallable = Callable[[Any, dict[str, Any]], bool | str | None | Awaitable[bool | str | None]]


@dataclass(frozen=True)
class PolicyRule:
    check: PolicyCallable
    name: str
    description: str = ""

    async def evaluate(self, context: Any, arguments: dict[str, Any]) -> str | None:
        decision = self.check(context, arguments)
        if inspect.isawaitable(decision):
            decision = await decision

        if decision is False:
            return f"policy denied: {self.name}"
        if isinstance(decision, str) and decision:
            return decision
        return None


@dataclass(frozen=True)
class SideEffectMetadata:
    read_only: bool = False
    idempotent: bool = False
    destructive: bool = False
    external_network: bool = False
    money_movement: bool = False
    writes_data: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {
            "read_only": self.read_only,
            "idempotent": self.idempotent,
            "destructive": self.destructive,
            "external_network": self.external_network,
            "money_movement": self.money_movement,
            "writes_data": self.writes_data,
        }


WINDOWS = {
    "second": 1,
    "minute": 60,
    "hour": 60 * 60,
    "day": 24 * 60 * 60,
}


def parse_rate_limit(expression: str) -> RateLimitRule:
    parts = [part.strip().lower() for part in expression.split("/")]
    if len(parts) != 3:
        raise ValueError(
            "rate limits must use the format '<count>/<window>/<scope>', "
            "for example '10/hour/user'"
        )

    limit_text, window_text, per = parts
    try:
        limit = int(limit_text)
    except ValueError as exc:
        raise ValueError("rate limit count must be an integer") from exc
    if limit < 1:
        raise ValueError("rate limit count must be at least 1")

    window_seconds = _parse_window(window_text)
    if per not in {"user", "actor", "global", "tool"}:
        raise ValueError("rate limit scope must be one of: user, actor, global, tool")

    return RateLimitRule(
        limit=limit,
        window_seconds=window_seconds,
        per=per,
        expression=expression,
    )


def redact_data(value: Any, fields: set[str]) -> Any:
    if not fields:
        return value
    normalized = {field.lower() for field in fields}
    return _redact(value, normalized)


def _parse_window(window: str) -> int:
    window = window.removesuffix("s")
    if window in WINDOWS:
        return WINDOWS[window]

    pieces = window.split()
    if len(pieces) == 2:
        count_text, unit = pieces
        unit = unit.removesuffix("s")
        if unit in WINDOWS:
            return int(count_text) * WINDOWS[unit]

    raise ValueError("rate limit window must be second, minute, hour, or day")


def _redact(value: Any, fields: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in fields else _redact(item, fields)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, fields) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, fields) for item in value)
    return value


def _is_over(value: Any, threshold: Any) -> bool:
    try:
        return float(value) > float(threshold)
    except (TypeError, ValueError):
        return False


def _is_at_or_over(value: Any, threshold: Any) -> bool:
    try:
        return float(value) >= float(threshold)
    except (TypeError, ValueError):
        return False
