from __future__ import annotations

from typing import Any

from .core import ToolRampart, ToolDefinition


def export_tools(shield: ToolRampart) -> dict[str, list[dict[str, Any]]]:
    return {"tools": [tool_to_mcp(tool) for tool in shield.list_tools()]}


def tool_to_mcp(tool: ToolDefinition) -> dict[str, Any]:
    schema = mcp_input_schema(tool)
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": schema,
        "outputSchema": tool.output_schema,
        "annotations": {
            "title": tool.name,
            "readOnlyHint": tool.side_effects.read_only,
            "destructiveHint": tool.side_effects.destructive,
            "idempotentHint": tool.side_effects.idempotent,
            "openWorldHint": tool.side_effects.external_network,
        },
        "x-toolrampart": {
            "scope": tool.required_scope,
            "approval_required": bool(tool.approval_policy),
            "rate_limit": tool.rate_limit_rule.expression if tool.rate_limit_rule else None,
            "redacts": sorted(tool.redact_fields),
            "side_effects": tool.side_effects.as_dict(),
        },
    }


def mcp_input_schema(tool: ToolDefinition) -> dict[str, Any]:
    schema = tool.input_model.model_json_schema()
    properties = schema.setdefault("properties", {})
    properties["_toolrampart_approval_id"] = {
        "description": "Optional ToolRampart approval request ID for approval-gated tools.",
        "title": "ToolRampart Approval Id",
        "type": "string",
    }
    properties["_toolrampart_idempotency_key"] = {
        "description": "Optional ToolRampart idempotency key for safe retries.",
        "title": "ToolRampart Idempotency Key",
        "type": "string",
    }
    return schema
