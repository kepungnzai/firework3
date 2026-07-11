"""Thin async helper to call remote MCP tools over Streamable HTTP.

Both the web-form edge service and the agent orchestrator use this to invoke
the resource-details, calendar, and email MCP servers. Tool results are parsed
from the MCP structured/text content back into Python objects.
"""

from __future__ import annotations

import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def call_tool(url: str, tool: str, arguments: dict[str, Any], api_key: str | None = None) -> Any:
    """Open a session to a remote MCP server, invoke `tool`, return its result."""
    headers = {"x-api-key": api_key} if api_key else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            return _parse_result(result)


def _parse_result(result: Any) -> Any:
    """Prefer structured content; fall back to parsing the first text block."""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        # FastMCP wraps scalar/list returns under a "result" key.
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
    return None