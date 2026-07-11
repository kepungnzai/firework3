"""Orchestration + audit tests: verify the agent performs the correct next-steps
and that the full lifecycle can be reconstructed from the audit log."""

from __future__ import annotations

import uuid

import pytest

from apptshared.schemas import (
    AppointmentRequest,
    BookingStatus,
    CancellationRequest,
    RequestEnvelope,
    RescheduleRequest,
)

from app import repository
from app.agent import process
from app.audit import reconstruct_timeline
from tests.conftest import FakeTools, monday_slot


def _env(payload) -> RequestEnvelope:
    return RequestEnvelope(correlation_id=str(uuid.uuid4()), payload=payload)


async def test_appointment_happy_path(make_booking):
    slot = monday_slot(10)
    booking_id = make_booking(slot)
    tools = FakeTools()

    payload = AppointmentRequest(
        booking_id=booking_id,
        resource="Dr Lee",
        patient_email="patient@example.com",
        idempotency_key=f"key-{booking_id}",
        slot=slot,
    )
    result = await process(_env(payload), tools)

    assert result.status == BookingStatus.confirmed
    assert tools.tool_names == [
        "get_resource",
        "get_opening_hours",
        "get_busy_slots",
        "get_resource",
        "create_event",
        "send_email",  # patient confirmation
        "send_email",  # resource notification
    ]
    assert repository.get_status(booking_id) == BookingStatus.confirmed
    # Audit timeline reconstructable start-to-end.
    timeline = reconstruct_timeline(booking_id)
    events = [e.event_type for e in timeline]
    assert events == ["guardrail_passed", "appointment_confirmed"]


async def test_cancellation_offers_reschedule(make_booking):
    slot = monday_slot(11)
    booking_id = make_booking(slot, status="confirmed", event_id="evt-existing")
    # Seed the fake calendar so cancel_event finds the event.
    tools = FakeTools()
    tools.calendar["evt-existing"] = {"start": slot.start, "end": slot.end}

    payload = CancellationRequest(
        booking_id=booking_id,
        resource="Dr Lee",
        patient_email="patient@example.com",
        idempotency_key=f"cancel-{booking_id}",
        slot=slot,
    )
    result = await process(_env(payload), tools)

    assert result.status == BookingStatus.reschedule_offered
    assert "cancel_event" in tools.tool_names
    timeline = [e.event_type for e in reconstruct_timeline(booking_id)]
    assert timeline == [
        "guardrail_passed",
        "appointment_cancelled",
        "reschedule_offered",
    ]


async def test_reschedule_moves_event(make_booking):
    slot = monday_slot(12)
    booking_id = make_booking(slot, status="confirmed", event_id="evt-1")
    tools = FakeTools()
    tools.calendar["evt-1"] = {"start": slot.start, "end": slot.end}

    new_slot = monday_slot(14)
    payload = RescheduleRequest(
        booking_id=booking_id,
        resource="Dr Lee",
        patient_email="patient@example.com",
        idempotency_key=f"resched-{booking_id}",
        old_slot=slot,
        new_slot=new_slot,
    )
    result = await process(_env(payload), tools)

    assert result.status == BookingStatus.rescheduled
    assert "update_event" in tools.tool_names
    assert tools.calendar["evt-1"]["start"] == new_slot.start


async def test_reschedule_to_taken_slot_rejected(make_booking):
    slot = monday_slot(12)
    booking_id = make_booking(slot, status="confirmed", event_id="evt-1")
    tools = FakeTools()
    tools.calendar["evt-1"] = {"start": slot.start, "end": slot.end}
    taken = monday_slot(15)
    tools.busy = [taken]

    payload = RescheduleRequest(
        booking_id=booking_id,
        resource="Dr Lee",
        patient_email="patient@example.com",
        idempotency_key=f"resched-{booking_id}",
        old_slot=slot,
        new_slot=taken,
    )
    result = await process(_env(payload), tools)

    assert result.reason == "slot_already_booked"
    assert "update_event" not in tools.tool_names


async def test_reschedule_outside_hours_rejected(make_booking):
    slot = monday_slot(12)
    booking_id = make_booking(slot, status="confirmed", event_id="evt-1")
    tools = FakeTools()
    tools.calendar["evt-1"] = {"start": slot.start, "end": slot.end}

    payload = RescheduleRequest(
        booking_id=booking_id,
        resource="Dr Lee",
        patient_email="patient@example.com",
        idempotency_key=f"resched-{booking_id}",
        old_slot=slot,
        new_slot=monday_slot(18),  # past closing time
    )
    result = await process(_env(payload), tools)
    assert result.reason == "outside_opening_hours"


async def test_idempotent_duplicate_skipped(make_booking):
    slot = monday_slot(10)
    booking_id = make_booking(slot, status="confirmed", event_id="evt-1")
    tools = FakeTools()

    payload = AppointmentRequest(
        booking_id=booking_id,
        resource="Dr Lee",
        patient_email="patient@example.com",
        idempotency_key=f"key-{booking_id}",
        slot=slot,
    )
    # Booking is already terminal (confirmed) -> processing is a no-op.
    result = await process(_env(payload), tools)
    assert result.status == BookingStatus.confirmed
    assert tools.tool_names == []  # no side effects


async def test_double_book_second_request_rejected(make_booking):
    """The DB unique index is the authoritative guard: a second *active* booking
    for the same resource/slot cannot even be created (closes the race window)."""
    from sqlalchemy.exc import IntegrityError

    slot = monday_slot(9)
    first = make_booking(slot, status="confirmed")
    tools = FakeTools()

    p1 = AppointmentRequest(
        booking_id=first,
        resource="Dr Lee",
        patient_email="patient@example.com",
        idempotency_key=f"key-{first}",
        slot=slot,
    )
    r1 = await process(_env(p1), tools)
    assert r1.status == BookingStatus.confirmed

    # Attempting a second active booking at the same slot is blocked by the DB.
    with pytest.raises(IntegrityError):
        make_booking(slot, status="pending")