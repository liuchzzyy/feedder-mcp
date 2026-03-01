"""MCP server entry point for feedder-mcp."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from src.config.settings import get_settings
from src.handlers.prompts import PromptHandler
from src.handlers.tools import ToolHandler

try:  # Optional import for environments without MCP installed
    from mcp.server import Server  # type: ignore[import-untyped]
    from mcp.server.stdio import stdio_server  # type: ignore[import-untyped]
    from mcp.types import (  # type: ignore[import-untyped]
        CallToolResult,
        GetPromptResult,
        ListPromptsResult,
        ListToolsResult,
        TextContent,
    )

    _MCP_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - only for missing MCP
    Server = None  # type: ignore[assignment]
    stdio_server = None  # type: ignore[assignment]
    CallToolResult = None  # type: ignore[assignment]
    ListToolsResult = None  # type: ignore[assignment]
    ListPromptsResult = None  # type: ignore[assignment]
    GetPromptResult = None  # type: ignore[assignment]
    TextContent = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR = exc


def _extract_name_and_args(request: Any) -> tuple[str, dict]:
    params = getattr(request, "params", None)
    if params is None:
        params = request
    name = getattr(params, "name", None) or getattr(request, "name", None)
    arguments = (
        getattr(params, "arguments", None)
        or getattr(request, "arguments", None)
        or {}
    )
    if not name:
        raise ValueError("Tool request missing name")
    if arguments is None:
        arguments = {}
    return str(name), dict(arguments)


def _extract_prompt_args(request: Any) -> tuple[str, dict]:
    params = getattr(request, "params", None)
    if params is None:
        params = request
    name = getattr(params, "name", None) or getattr(request, "name", None)
    arguments = (
        getattr(params, "arguments", None)
        or getattr(request, "arguments", None)
        or {}
    )
    if not name:
        raise ValueError("Prompt request missing name")
    return str(name), dict(arguments)


async def serve() -> None:
    """Run the MCP server using stdio transport."""
    if Server is None or stdio_server is None:
        raise ImportError(
            "mcp package is required to run the server"
        ) from _MCP_IMPORT_ERROR

    tool_handler = ToolHandler()
    prompt_handler = PromptHandler()

    server = Server(get_settings().server_name)

    @server.list_tools()
    async def _list_tools() -> Any:
        return ListToolsResult(tools=tool_handler.get_tools())

    @server.call_tool()
    async def _call_tool(request: Any) -> Any:
        name, arguments = _extract_name_and_args(request)
        result_text, is_error = await tool_handler.handle_tool(name, arguments)
        return CallToolResult(
            content=[TextContent(type="text", text=result_text)],
            isError=is_error,
        )

    @server.list_prompts()
    async def _list_prompts() -> Any:
        return ListPromptsResult(prompts=prompt_handler.get_prompts())

    @server.get_prompt()
    async def _get_prompt(request: Any) -> Any:
        name, arguments = _extract_prompt_args(request)
        messages = prompt_handler.render_prompt(name, arguments)
        return GetPromptResult(messages=messages)

    keepalive = os.environ.get("MCP_STDIO_KEEPALIVE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    while True:
        try:
            async with stdio_server(server):
                await server.run()
        except ExceptionGroup:
            # Graceful shutdown when stdio is closed or client disconnects.
            if not keepalive:
                return
            await asyncio.sleep(0.25)


def main() -> None:
    """Entry point for running the MCP server."""
    asyncio.run(serve())


if __name__ == "__main__":
    main()

