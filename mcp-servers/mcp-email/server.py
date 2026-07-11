"""Remote MCP server: send email.

Tool:
- send_email(to, subject, body, cc)

Uses the provider abstraction: Gmail by default, in-memory fake when
FAKE_PROVIDERS=true.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from providers import build_provider

mcp = FastMCP("email", host="0.0.0.0", port=8083)
_provider = build_provider()


@mcp.tool()
def send_email(
    to: str, subject: str, body: str, cc: list[str] | None = None
) -> dict:
    """Send a plain-text email and return the provider message id."""
    message_id = _provider.send_email(to, subject, body, cc)
    return {"message_id": message_id}


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)