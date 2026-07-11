"""Availability computation for the web-form service.

availableSlots = candidate slots within opening hours
                 - busy slots on the resource calendar (via MCP calendar tool)
                 - active DB holds (pending/confirmed bookings)

This is a *preview*. The agent re-checks authoritatively at booking time to
close the race window (enforced by the DB unique index).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from apptshared.config import get_settings
from apptshared.db import session_scope
from apptshared.mcpclient import call_tool
from apptshared.models import Booking
from apptshared.schemas import Slot
from apptshared.timeutils import local_slots_for_day, parse_hhmm


async def available_slots(resource: str, day: datetime) -> list[Slot]:
    settings = get_settings()

    hours = await call_tool(
        settings.mcp_resource_details_url,
        "get_opening_hours",
        {"resource": resource},
        settings.mcp_api_key,
    )
    resource_info = await call_tool(
        settings.mcp_resource_details_url,
        "get_resource",
        {"resource": resource},
        settings.mcp_api_key,
    )
    if not resource_info or resource_info.get("error"):
        return []

    tz_name = hours.get("timezone", settings.default_timezone)
    dow = str(day.weekday())
    day_hours = hours.get("days", {}).get(dow)
    if not day_hours:
        return []  # closed that day

    candidates = local_slots_for_day(
        day=day,
        opening_start=parse_hhmm(day_hours["start"]),
        opening_end=parse_hhmm(day_hours["end"]),
        tz_name=tz_name,
        slot_minutes=settings.slot_minutes,
    )
    if not candidates:
        return []

    window_start = candidates[0].start
    window_end = candidates[-1].end
    calendar_id = resource_info["calendar_id"]

    busy_raw = await call_tool(
        settings.mcp_calendar_url,
        "get_busy_slots",
        {
            "calendar_id": calendar_id,
            "start_iso": window_start.isoformat(),
            "end_iso": window_end.isoformat(),
        },
        settings.mcp_api_key,
    )
    busy = [
        Slot(
            start=datetime.fromisoformat(b["start"]),
            end=datetime.fromisoformat(b["end"]),
        )
        for b in (busy_raw or [])
    ]

    holds = _active_holds(resource_info["id"], window_start, window_end)

    free: list[Slot] = []
    for slot in candidates:
        if any(slot.overlaps(b) for b in busy):
            continue
        if any(slot.overlaps(h) for h in holds):
            continue
        free.append(slot)
    return free


def _active_holds(resource_id: str, start: datetime, end: datetime) -> list[Slot]:
    for session in session_scope():
        rows = session.execute(
            select(Booking).where(
                Booking.resource_id == resource_id,
                Booking.status.in_(["pending", "confirmed"]),
                Booking.start_utc < end,
                Booking.end_utc > start,
            )
        )
        return [
            Slot(start=_as_utc(b.start_utc), end=_as_utc(b.end_utc))
            for b in rows.scalars()
        ]
    return []


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
