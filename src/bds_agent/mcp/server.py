from __future__ import annotations

import logging
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from bds_agent.client import BdsClientError
from bds_agent.mcp.registry import (
    EndpointTool,
    build_endpoint_tools,
    find_tool,
    invoke_tool,
    to_mcp_tools,
)

logger = logging.getLogger(__name__)


def _make_server(
    tools: list[EndpointTool],
    *,
    base_url: str,
    api_key: str,
) -> Server:
    mcp_tools = to_mcp_tools(tools)
    server = Server(
        "bds-agent",
        version="0.1.0",
        instructions=(
            "Powerloom BDS HTTP tools (Bearer auth). Each tool maps to one route from "
            "the endpoint catalog. Use GET snapshot/stream tools with your pool addresses "
            "and epoch parameters as documented in each tool description."
        ),
    )

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return mcp_tools

    @server.call_tool()
    async def handle_call_tool(
        name: str,
        arguments: dict | None,
    ) -> dict[str, Any] | types.CallToolResult:
        spec = find_tool(tools, name)
        if spec is None:
            return types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=f"Unknown tool: {name!r}"),
                ],
                isError=True,
            )
        try:
            return await invoke_tool(
                spec,
                dict(arguments or {}),
                base_url=base_url,
                api_key=api_key,
            )
        except ValueError as e:
            logger.warning("MCP tool arg error: %s", e)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(e))],
                isError=True,
            )
        except BdsClientError as e:
            logger.warning("BDS HTTP error: %s", e)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(e))],
                isError=True,
            )
        except Exception as e:
            logger.exception("MCP tool failure")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(e))],
                isError=True,
            )

    return server


async def run_mcp_stdio(
    *,
    catalog: dict[str, Any],
    base_url: str,
    api_key: str,
) -> None:
    """
    Run an MCP server on stdio. Do not write to stdout (logging must use stderr).
    """
    tools = build_endpoint_tools(catalog)
    if not tools:
        logger.error("No endpoints in catalog; refusing to start MCP server.")
        raise SystemExit(2)

    server = _make_server(tools, base_url=base_url, api_key=api_key)
    init = server.create_initialization_options()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            init,
            raise_exceptions=False,
        )
