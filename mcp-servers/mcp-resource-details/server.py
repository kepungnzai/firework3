"""Remote MCP server: resource details + organisation opening hours.

Tools:
- list_resources()            -> [{id, name, email, calendar_id, timezone}]
- get_resource(resource)      -> {id, name, email, calendar_id, timezone}
- get_opening_hours(resource) -> {timezone, days: {dow: {start, end}}}

Backed by Postgres (via apptshared). Runs over Streamable HTTP so the agent
orchestrator can reach it as a remote tool.
"""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from apptshared.db import session_scope
from apptshared.models import OpeningHours, Resource

logger = logging.getLogger(__name__)

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
    logger.info("list_resources called")
    for session in session_scope():
        rows = session.execute(
            select(Resource).where(Resource.active.is_(True))
        ).scalars()
        result = [
            {
                "id": r.id,
                "name": r.name,
                "email": r.email,
                "calendar_id": r.calendar_id,
                "timezone": r.timezone,
            }
            for r in rows
        ]
        logger.info("list_resources returning %d resources", len(result))
        return result
    logger.warning("list_resources: no database session available")
    return []


@mcp.tool()
def get_resource(resource: str) -> dict:
    """Get a single resource by id or name. Includes email for notifications."""
    logger.info("get_resource called with resource=%s", resource)
    for session in session_scope():
        r = _resource_by_name_or_id(session, resource)
        if not r:
            logger.warning("get_resource: resource '%s' not found", resource)
            return {"error": "not_found", "resource": resource}
        logger.info("get_resource: found resource '%s' (id=%s)", r.name, r.id)
        return {
            "id": r.id,
            "name": r.name,
            "email": r.email,
            "calendar_id": r.calendar_id,
            "timezone": r.timezone,
        }
    logger.warning("get_resource: no database session available")
    return {"error": "not_found", "resource": resource}


@mcp.tool()
def get_opening_hours(resource: str | None = None) -> dict:
    """Return opening hours. Resource-specific hours override org hours when set.

    Response: {"timezone": str, "days": {"0": {"start": "09:00", "end": "17:00"}, ...}}
    """
    logger.info("get_opening_hours called with resource=%s", resource)
    for session in session_scope():
        tz = "UTC"
        resource_id = None
        if resource:
            r = _resource_by_name_or_id(session, resource)
            if r:
                tz = r.timezone
                resource_id = r.id
                logger.info("get_opening_hours: resolved resource '%s' -> id=%s, tz=%s", resource, resource_id, tz)
            else:
                logger.warning("get_opening_hours: resource '%s' not found, falling back to org hours", resource)

        rows = list(
            session.execute(
                select(OpeningHours).where(
                    OpeningHours.scope == "resource",
                    OpeningHours.resource_id == resource_id,
                )
            ).scalars()
        )
        if rows:
            logger.info("get_opening_hours: using resource-specific hours (%d rows) for resource_id=%s", len(rows), resource_id)
        else:
            rows = list(
                session.execute(
                    select(OpeningHours).where(OpeningHours.scope == "org")
                ).scalars()
            )
            logger.info("get_opening_hours: using org-wide hours (%d rows)", len(rows))

        days = {
            str(row.day_of_week): {
                "start": row.start_time.strftime("%H:%M"),
                "end": row.end_time.strftime("%H:%M"),
            }
            for row in rows
        }
        logger.info("get_opening_hours: returning tz=%s with %d days", tz, len(days))
        return {"timezone": tz, "days": days}
    logger.warning("get_opening_hours: no database session available")
    return {"timezone": "UTC", "days": {}}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    logger.info("Starting resource-details server on transport=%s", transport)
    mcp.run(transport=transport)
