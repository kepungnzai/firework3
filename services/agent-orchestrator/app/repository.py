"""Booking persistence helpers used by the agent orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from apptshared.db import session_scope
from apptshared.models import Booking
from apptshared.schemas import BookingStatus, Slot


def get_status(booking_id: str) -> BookingStatus | None:
    for session in session_scope():
        b = session.get(Booking, booking_id)
        return BookingStatus(b.status) if b else None
    return None


def get_calendar_event_id(booking_id: str) -> str | None:
    for session in session_scope():
        b = session.get(Booking, booking_id)
        return b.gcal_event_id if b else None
    return None


def set_status(booking_id: str, status: BookingStatus) -> None:
    for session in session_scope():
        b = session.get(Booking, booking_id)
        if b:
            b.status = status.value
            b.updated_at = datetime.now(timezone.utc)


def set_event_id(booking_id: str, event_id: str | None) -> None:
    for session in session_scope():
        b = session.get(Booking, booking_id)
        if b:
            b.gcal_event_id = event_id


def set_slot(booking_id: str, slot: Slot) -> None:
    for session in session_scope():
        b = session.get(Booking, booking_id)
        if b:
            b.start_utc = slot.start
            b.end_utc = slot.end


def already_processed(idempotency_key: str, terminal_only: bool = False) -> bool:
    """True if a booking with this idempotency key is already in a terminal state
    (used to make queue processing idempotent)."""
    for session in session_scope():
        b = session.execute(
            select(Booking).where(Booking.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if not b:
            return False
        return b.status in ("confirmed", "cancelled", "rescheduled")
    return False