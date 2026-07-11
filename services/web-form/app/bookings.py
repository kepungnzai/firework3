"""Booking creation/lookup for the web-form service.

Creating an appointment writes a `pending` booking (the DB unique index is the
authoritative guard against double-booking) and publishes a request envelope to
the queue for the agent to process.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from apptshared.config import get_settings
from apptshared.db import session_scope
from apptshared.mcpclient import call_tool
from apptshared.models import Booking, Patient
from apptshared.queue import build_queue
from apptshared.schemas import (
    AppointmentRequest,
    CancellationRequest,
    RequestEnvelope,
    RescheduleRequest,
    Slot,
)


class BookingError(Exception):
    pass


async def _resolve_resource_id(resource: str) -> str:
    settings = get_settings()
    info = await call_tool(
        settings.mcp_resource_details_url,
        "get_resource",
        {"resource": resource},
        settings.mcp_api_key,
    )
    if not info or info.get("error"):
        raise BookingError(f"Unknown resource: {resource}")
    return info["id"]


def _patient_id(session, email: str) -> str:
    patient = session.execute(
        select(Patient).where(Patient.email == email)
    ).scalar_one_or_none()
    if not patient:
        raise BookingError("Patient not found; verify your email first.")
    return patient.id


async def create_appointment(resource: str, email: str, slot: Slot) -> str:
    resource_id = await _resolve_resource_id(resource)
    booking_id = f"bk-{uuid.uuid4().hex[:10]}"
    idem = f"appt-{resource_id}-{slot.start.isoformat()}"

    try:
        for session in session_scope():
            patient_id = _patient_id(session, email)
            session.add(
                Booking(
                    id=booking_id,
                    patient_id=patient_id,
                    resource_id=resource_id,
                    start_utc=slot.start,
                    end_utc=slot.end,
                    status="pending",
                    idempotency_key=idem,
                )
            )
    except IntegrityError as exc:
        raise BookingError("That slot is no longer available.") from exc

    envelope = RequestEnvelope(
        correlation_id=str(uuid.uuid4()),
        payload=AppointmentRequest(
            booking_id=booking_id,
            resource=resource,
            patient_email=email,
            idempotency_key=idem,
            slot=slot,
        ),
    )
    build_queue().publish(envelope)
    return booking_id


async def request_cancellation(booking_id: str, email: str) -> str:
    booking = _load_booking(booking_id)
    envelope = RequestEnvelope(
        correlation_id=str(uuid.uuid4()),
        payload=CancellationRequest(
            booking_id=booking_id,
            resource=booking["resource_id"],
            patient_email=email,
            idempotency_key=f"cancel-{booking_id}",
            slot=Slot(start=booking["start_utc"], end=booking["end_utc"]),
        ),
    )
    build_queue().publish(envelope)
    return booking_id


async def request_reschedule(booking_id: str, email: str, new_slot: Slot) -> str:
    booking = _load_booking(booking_id)
    envelope = RequestEnvelope(
        correlation_id=str(uuid.uuid4()),
        payload=RescheduleRequest(
            booking_id=booking_id,
            resource=booking["resource_id"],
            patient_email=email,
            idempotency_key=f"resched-{booking_id}-{new_slot.start.isoformat()}",
            old_slot=Slot(start=booking["start_utc"], end=booking["end_utc"]),
            new_slot=new_slot,
        ),
    )
    build_queue().publish(envelope)
    return booking_id


def _load_booking(booking_id: str) -> dict:
    for session in session_scope():
        b = session.get(Booking, booking_id)
        if not b:
            raise BookingError(f"Unknown booking: {booking_id}")
        return {
            "resource_id": b.resource_id,
            "start_utc": _as_utc(b.start_utc),
            "end_utc": _as_utc(b.end_utc),
        }
    raise BookingError(f"Unknown booking: {booking_id}")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
