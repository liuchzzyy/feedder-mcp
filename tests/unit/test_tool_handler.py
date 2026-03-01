"""Unit tests for MCP tool handler."""

import json

import pytest

from src.handlers.tools import ToolHandler
from src.models.enums import ToolName


@pytest.mark.asyncio
async def test_handle_tool_returns_error_flag_for_failure():
    handler = ToolHandler()
    text, is_error = await handler.handle_tool("unknown_tool", {})

    payload = json.loads(text)
    assert is_error is True
    assert payload["ok"] is False


@pytest.mark.asyncio
async def test_enrich_tool_rejects_invalid_provider():
    handler = ToolHandler()
    papers_json = "[]"

    text, is_error = await handler.handle_tool(
        ToolName.ENRICH.value,
        {"papers_json": papers_json, "provider": "invalid"},
    )

    payload = json.loads(text)
    assert is_error is True
    assert payload["ok"] is False
