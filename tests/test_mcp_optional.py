from __future__ import annotations

import asyncio

import pytest

from toolrampart import ToolRampart, side_effects
from toolrampart.mcp_server import create_mcp_server

mcp_types = pytest.importorskip("mcp.types")


def test_low_level_mcp_server_lists_and_calls_tools():
    shield = ToolRampart(audit_path=":memory:")

    @shield.tool
    @side_effects(read_only=True, idempotent=True)
    def hello(name: str) -> dict:
        return {"hello": name}

    server = create_mcp_server(shield)

    async def run() -> None:
        listed = await server.request_handlers[mcp_types.ListToolsRequest](
            mcp_types.ListToolsRequest()
        )
        tools = listed.root.tools
        assert tools[0].name == "hello"
        assert tools[0].annotations.readOnlyHint is True
        assert tools[0].annotations.idempotentHint is True

        called = await server.request_handlers[mcp_types.CallToolRequest](
            mcp_types.CallToolRequest(
                params={
                    "name": "hello",
                    "arguments": {"name": "Ada"},
                }
            )
        )
        assert called.root.isError is False
        assert called.root.structuredContent["data"] == {"hello": "Ada"}

    asyncio.run(run())
