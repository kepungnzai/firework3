"""Remote MCP server: resource details + organisation opening hours.

Tools:
- list_resources()            -> [{id, name, email, calendar_id, timezone}]
- get_resource(resource)      -> {id, name, email, calendar_id, timezone}
- get_opening_hours(resource) -> {timezone, days: {dow: {start, end}}}

Backed by Postgres (via apptshared). Runs over Streamable HTTP so the agent
orchestrator can reach it as a remote tool.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from apptshared.db import session_scope
from apptshared.models import OpeningHours, Resource

mcp = FastMCP("resource-details", host="0.0.0.0", port=8081)


def _resource_by_name_or_id(session, resource: str) -> Resource | None:
    row = session.get(Resource, resource)
    if row:
        return row
    return session.execute(
        select(Resource).where(Resource.name == resource)
    ).scalar_one_or_none()


@mcp.tool()
def list_resources() -> list[dict]:
    """List all active bookable resources."""
    for session in session_scope():
        rows = session.execute(
            select(Resource).where(Resource.active.is_(True))
        ).scalars()
        return [
            {
                "id": r.id,
                "name": r.name,
                "email": r.email,
                "calendar_id": r.calendar_id,
                "timezone": r.timezone,
            }
            for r in rows
        ]
    return []


@mcp.tool()
def get_resource(resource: str) -> dict:
    """Get a single resource by id or name. Includes email for notifications."""
    for session in session_scope():
        r = _resource_by_name_or_id(session, resource)
        if not r:
            return {"error": "not_found", "resource": resource}
        return {
            "id": r.id,
            "name": r.name,
            "email": r.email,
            "calendar_id": r.calendar_id,
            "timezone": r.timezone,
        }
    return {"error": "not_found", "resource": resource}


@mcp.tool()
def get_opening_hours(resource: str | None = None) -> dict:
    """Return opening hours. Resource-specific hours override org hours when set.

    Response: {"timezone": str, "days": {"0": {"start": "09:00", "end": "17:00"}, ...}}
    """
    for session in session_scope():
        tz = "UTC"
        resource_id = None
        if resource:
            r = _resource_by_name_or_id(session, resource)
            if r:
                tz = r.timezone
                resource_id = r.id

        rows = list(
            session.execute(
                select(OpeningHours).where(
                    OpeningHours.scope == "resource",
                    OpeningHours.resource_id == resource_id,
                )
            ).scalars()
        )
        if not rows:
            rows = list(
                session.execute(
                    select(OpeningHours).where(OpeningHours.scope == "org")
                ).scalars()
            )

        days = {
            str(row.day_of_week): {
                "start": row.start_time.strftime("%H:%M"),
                "end": row.end_time.strftime("%H:%M"),
            }
            for row in rows
        }
        return {"timezone": tz, "days": days}
    return {"timezone": "UTC", "days": {}}


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)