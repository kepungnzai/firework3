"""Deterministic validation guardrail (the 'Agent 1' role).

Pure, code-level checks that gate every effectful request. No LLM involved, so
results are reproducible and unit-testable in milliseconds. If any check fails
the request is rejected with a machine-readable reason and no tools that mutate
state are called.

Checks:
1. Patient is verified (proved control of their email).
2. The target slot is within the resource's opening hours.
3. The target slot is not already busy on the resource's calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from apptshared.db import session_scope
from apptshared.models import Patient
from apptshared.schemas import (
    AppointmentRequest,
    CancellationRequest,
    RescheduleRequest,
    Slot,
)
from apptshared.timeutils import parse_hhmm, within_opening_hours

from app.tools import Tools


@dataclass
class GuardrailResult:
    ok: bool
    reason: str | None = None


def _patient_verified(email: str) -> bool:
    for session in session_scope():
        patient = session.execute(
            select(Patient).where(Patient.email == email)
        ).scalar_one_or_none()
        return bool(patient and patient.verified_at is not None)
    return False


def _slot_within_hours(hours: dict, slot: Slot) -> bool:
    from zoneinfo import ZoneInfo

    tz_name = hours.get("timezone", "UTC")
    dow = str(slot.start.astimezone(ZoneInfo(tz_name)).weekday())
    day_hours = hours.get("days", {}).get(dow)
    if not day_hours:
        return False
    return within_opening_hours(
        slot, parse_hhmm(day_hours["start"]), parse_hhmm(day_hours["end"]), tz_name
    )


async def _slot_is_free(tools: Tools, calendar_id: str, slot: Slot) -> bool:
    busy_raw = await tools.get_busy_slots(calendar_id, slot.start, slot.end)
    for b in busy_raw or []:
        busy = Slot(
            start=datetime.fromisoformat(b["start"]),
            end=datetime.fromisoformat(b["end"]),
        )
        if slot.overlaps(busy):
            return False
    return True


async def validate(
    payload: AppointmentRequest | CancellationRequest | RescheduleRequest,
    tools: Tools,
) -> GuardrailResult:
    # 1. Patient legitimacy
    if not _patient_verified(payload.patient_email):
        return GuardrailResult(False, "patient_not_verified")

    resource = await tools.get_resource(payload.resource)
    if not resource or resource.get("error"):
        return GuardrailResult(False, "unknown_resource")
    calendar_id = resource["calendar_id"]

    # Cancellations don't need hours/availability checks.
    if isinstance(payload, CancellationRequest):
        return GuardrailResult(True)

    target = payload.slot if isinstance(payload, AppointmentRequest) else payload.new_slot
    hours = await tools.get_opening_hours(payload.resource)

    # 2. Opening hours
    if not _slot_within_hours(hours, target):
        return GuardrailResult(False, "outside_opening_hours")

    # 3. Availability (double-book)
    if not await _slot_is_free(tools, calendar_id, target):
        return GuardrailResult(False, "slot_already_booked")

    return GuardrailResult(True)