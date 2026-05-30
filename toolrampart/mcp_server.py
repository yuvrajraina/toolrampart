from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from ._version import __version__
from .core import ToolRampart, ToolContext, default_rampart
from .mcp import mcp_input_schema


def create_mcp_server(shield: ToolRampart | None = None, *, name: str = "ToolRampart"):
    """Create a low-level MCP server backed by ToolRampart.

    The official MCP SDK is optional so the base REST/CLI framework stays small.
    Install it with `pip install toolrampart[mcp]`.
    """

    try:
        import mcp.types as types
        from mcp.server.lowlevel import Server
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "MCP server support requires the 'mcp' extra: pip install toolrampart[mcp]"
        ) from exc

    current_shield = shield or default_rampart
    server = Server(name)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = []
        for tool in current_shield.list_tools():
            kwargs = {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": mcp_input_schema(tool),
                "annotations": types.ToolAnnotations(
                    title=tool.name,
                    readOnlyHint=tool.side_effects.read_only,
                    destructiveHint=tool.side_effects.destructive,
                    idempotentHint=tool.side_effects.idempotent,
                    openWorldHint=tool.side_effects.external_network,
                ),
            }
            if tool.output_schema:
                kwargs["outputSchema"] = tool.output_schema
            tools.append(types.Tool(**kwargs))
        return tools

    @server.call_tool()
    async def call_tool(tool_name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        call_arguments = dict(arguments or {})
        approval_id = call_arguments.pop("_toolrampart_approval_id", None)
        idempotency_key = call_arguments.pop("_toolrampart_idempotency_key", None)
        context = ToolContext(
            actor=os.getenv("TOOLRAMPART_MCP_ACTOR", "mcp-client"),
            scopes=_mcp_scopes(),
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            source="mcp",
        )
        result = await current_shield.execute(tool_name, call_arguments, context)
        text = json.dumps(result.model_dump(), default=str, indent=2)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            structuredContent=result.model_dump(),
            isError=not result.ok,
        )

    return server


async def run_stdio(shield: ToolRampart | None = None, *, name: str = "ToolRampart") -> None:
    try:
        import mcp.server.stdio
        from mcp.server.lowlevel import NotificationOptions
        from mcp.server.models import InitializationOptions
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "MCP stdio support requires the 'mcp' extra: pip install toolrampart[mcp]"
        ) from exc

    server = create_mcp_server(shield, name=name)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=name,
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(run_stdio())


def _mcp_scopes() -> list[str]:
    return [
        scope.strip()
        for scope in os.getenv("TOOLRAMPART_MCP_SCOPES", "").split(",")
        if scope.strip()
    ]


if __name__ == "__main__":
    main()
