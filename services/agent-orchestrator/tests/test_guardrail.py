"""Guardrail unit tests — deterministic validation, no LLM, millisecond-fast."""

from __future__ import annotations

import uuid

from apptshared.schemas import AppointmentRequest

from app import guardrail
from tests.conftest import FakeTools, monday_slot


def _appointment(email: str, slot) -> AppointmentRequest:
    return AppointmentRequest(
        booking_id=f"bk-{uuid.uuid4().hex[:8]}",
        resource="Dr Lee",
        patient_email=email,
        idempotency_key=f"appt-{uuid.uuid4().hex[:8]}",
        slot=slot,
    )


async def test_unverified_patient_rejected(seed_resource, unverified_patient):
    tools = FakeTools()
    result = await guardrail.validate(_appointment(unverified_patient, monday_slot()), tools)
    assert not result.ok
    assert result.reason == "patient_not_verified"


async def test_within_hours_and_free_passes(seed_resource, verified_patient):
    tools = FakeTools()
    result = await guardrail.validate(_appointment(verified_patient, monday_slot(10)), tools)
    assert result.ok


async def test_outside_opening_hours_rejected(seed_resource, verified_patient):
    tools = FakeTools()
    # 18:00 Sydney is past the 17:00 close.
    result = await guardrail.validate(_appointment(verified_patient, monday_slot(18)), tools)
    assert not result.ok
    assert result.reason == "outside_opening_hours"


async def test_double_booked_rejected(seed_resource, verified_patient):
    tools = FakeTools()
    slot = monday_slot(9)
    tools.busy = [slot]  # calendar already busy at that slot
    result = await guardrail.validate(_appointment(verified_patient, slot), tools)
    assert not result.ok
    assert result.reason == "slot_already_booked"


async def test_unknown_resource_rejected(seed_resource, verified_patient):
    tools = FakeTools()

    async def _no_resource(resource: str):
        return {"error": "not_found"}

    tools.get_resource = _no_resource  # type: ignore[assignment]
    result = await guardrail.validate(_appointment(verified_patient, monday_slot(10)), tools)
    assert not result.ok
    assert result.reason == "unknown_resource"