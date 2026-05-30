from __future__ import annotations

import contextlib
from time import perf_counter
from typing import Any

from ._version import __version__


class Telemetry:
    def __init__(self, *, enabled: bool = True, service_name: str = "toolrampart") -> None:
        self.enabled = enabled
        self.service_name = service_name
        self.available = False
        self._trace = None
        self._status = None
        self._status_code = None
        self._invocations = None
        self._duration = None

        if not enabled:
            return

        try:
            from opentelemetry import metrics, trace
            from opentelemetry.trace import Status, StatusCode
        except ImportError:
            return

        self.available = True
        self._trace = trace
        self._status = Status
        self._status_code = StatusCode
        meter = metrics.get_meter("toolrampart", __version__)
        self._invocations = meter.create_counter(
            "toolrampart.tool.invocations",
            unit="1",
            description="ToolRampart tool invocations by status.",
        )
        self._duration = meter.create_histogram(
            "toolrampart.tool.duration",
            unit="s",
            description="ToolRampart tool invocation duration.",
        )

    def start_tool_span(self, *, tool_name: str, actor: str, source: str):
        if not self.available:
            return contextlib.nullcontext(_NoopSpan())
        tracer = self._trace.get_tracer("toolrampart", __version__)
        return tracer.start_as_current_span(
            "toolrampart.tool.invoke",
            attributes={
                "toolrampart.tool.name": tool_name,
                "toolrampart.actor": actor,
                "toolrampart.source": source,
            },
        )

    def checkpoint(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        if not self.available:
            return
        span = self._trace.get_current_span()
        span.add_event(f"toolrampart.{name}", attributes or {})

    def record_result(
        self,
        *,
        tool_name: str,
        status: str,
        duration_seconds: float,
        error_type: str | None = None,
        replayed: bool = False,
    ) -> None:
        if not self.available:
            return

        attributes = {
            "toolrampart.tool.name": tool_name,
            "toolrampart.status": status,
            "toolrampart.replayed": replayed,
        }
        if error_type:
            attributes["toolrampart.error_type"] = error_type

        self._invocations.add(1, attributes)
        self._duration.record(duration_seconds, attributes)

        span = self._trace.get_current_span()
        span.set_attribute("toolrampart.status", status)
        span.set_attribute("toolrampart.replayed", replayed)
        if error_type:
            span.set_attribute("toolrampart.error_type", error_type)
        if status in {"success", "requires_approval"}:
            span.set_status(self._status(self._status_code.OK))
        elif status != "rate_limited":
            span.set_status(self._status(self._status_code.ERROR))


class Timer:
    def __init__(self) -> None:
        self.started_at = perf_counter()

    @property
    def elapsed(self) -> float:
        return perf_counter() - self.started_at


class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        return None
