"""Timezone / slot helpers. All persisted times are UTC; resource-local times
are derived using the resource's IANA timezone."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from apptshared.schemas import Slot


def parse_hhmm(value: str) -> time:
    """Parse an 'HH:MM' opening-hours string into a time object."""
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def ensure_utc(dt: datetime) -> datetime:
    """Return a timezone-aware datetime in UTC."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not allowed; provide tz-aware value")
    return dt.astimezone(timezone.utc)


def local_slots_for_day(
    day: datetime,
    opening_start: time,
    opening_end: time,
    tz_name: str,
    slot_minutes: int,
) -> list[Slot]:
    """Generate the candidate slots for a given calendar day in the resource's
    timezone, returned as UTC `Slot`s.

    `day` only needs to carry the date; the time component is ignored.
    """
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(day.date(), opening_start, tzinfo=tz)
    end_local = datetime.combine(day.date(), opening_end, tzinfo=tz)

    slots: list[Slot] = []
    cursor = start_local
    step = timedelta(minutes=slot_minutes)
    while cursor + step <= end_local:
        slots.append(
            Slot(
                start=cursor.astimezone(timezone.utc),
                end=(cursor + step).astimezone(timezone.utc),
            )
        )
        cursor += step
    return slots


def within_opening_hours(
    slot: Slot,
    opening_start: time,
    opening_end: time,
    tz_name: str,
) -> bool:
    """True if the slot falls entirely within the opening hours (resource TZ)."""
    tz = ZoneInfo(tz_name)
    start_local = slot.start.astimezone(tz)
    end_local = slot.end.astimezone(tz)

    if start_local.date() != end_local.date():
        return False

    day_open = datetime.combine(start_local.date(), opening_start, tzinfo=tz)
    day_close = datetime.combine(start_local.date(), opening_end, tzinfo=tz)
    return day_open <= start_local and end_local <= day_close
