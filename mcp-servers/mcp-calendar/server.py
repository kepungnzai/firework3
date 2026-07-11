"""Remote MCP server: Google Calendar operations.

Tools:
- get_busy_slots(calendar_id, start_iso, end_iso)
- create_event(calendar_id, summary, start_iso, end_iso, attendees)
- cancel_event(calendar_id, event_id)
- update_event(calendar_id, event_id, start_iso, end_iso)

Uses the provider abstraction: real Google Calendar by default, in-memory fake
when FAKE_PROVIDERS=true.
"""

from __future__ import annotations

import os
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from providers import build_provider

mcp = FastMCP("calendar", host="0.0.0.0", port=8082)
_provider = build_provider()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


@mcp.tool()
def get_busy_slots(calendar_id: str, start_iso: str, end_iso: str) -> list[dict]:
    """Return busy intervals for a calendar within [start, end)."""
    return _provider.get_busy_slots(calendar_id, _dt(start_iso), _dt(end_iso))


@mcp.tool()
def create_event(
    calendar_id: str,
    summary: str,
    start_iso: str,
    end_iso: str,
    attendees: list[str] | None = None,
) -> dict:
    """Create a calendar event and return its provider event id."""
    event_id = _provider.create_event(
        calendar_id, summary, _dt(start_iso), _dt(end_iso), attendees
    )
    return {"event_id": event_id}


@mcp.tool()
def cancel_event(calendar_id: str, event_id: str) -> dict:
    """Delete a calendar event."""
    ok = _provider.cancel_event(calendar_id, event_id)
    return {"cancelled": ok}


@mcp.tool()
def update_event(
    calendar_id: str, event_id: str, start_iso: str, end_iso: str
) -> dict:
    """Move an existing calendar event to a new time window."""
    ok = _provider.update_event(calendar_id, event_id, _dt(start_iso), _dt(end_iso))
    return {"updated": ok}


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)