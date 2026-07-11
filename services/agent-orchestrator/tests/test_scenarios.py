"""JSON-driven scenario / eval suite.

Each fixture in tests/scenarios/*.json declares a setup, a request, and the
expected final status + ordered tool-call trace. This is the low-effort way to
add new orchestration cases: drop in a JSON file, no code required.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from apptshared.schemas import (
    AppointmentRequest,
    CancellationRequest,
    RequestEnvelope,
    RescheduleRequest,
)

from app.agent import process
from tests.conftest import FakeTools, monday_slot

SCENARIO_DIR = Path(__file__).parent / "scenarios"
SCENARIOS = sorted(SCENARIO_DIR.glob("*.json"))


def _ids(paths):
    return [p.stem for p in paths]


@pytest.mark.parametrize("path", SCENARIOS, ids=_ids(SCENARIOS))
async def test_scenario(path, make_booking):
    spec = json.loads(path.read_text(encoding="utf-8"))
    setup = spec["setup"]
    req = spec["request"]
    expected = spec["expected"]

    slot = monday_slot(req["hour"])
    booking_id = make_booking(
        slot, status=setup["booking_status"], event_id=setup.get("event_id")
    )

    tools = FakeTools()
    for ev in setup.get("calendar", []):
        s = monday_slot(ev["hour"])
        tools.calendar[ev["event_id"]] = {"start": s.start, "end": s.end}
    tools.busy = [monday_slot(h) for h in setup.get("busy", [])]

    common = dict(
        booking_id=booking_id,
        resource=req["resource"],
        patient_email="patient@example.com",
        idempotency_key=f"key-{uuid.uuid4().hex[:8]}",
    )
    if req["type"] == "appointment":
        payload = AppointmentRequest(slot=slot, **common)
    elif req["type"] == "cancellation":
        payload = CancellationRequest(slot=slot, **common)
    else:
        payload = RescheduleRequest(
            old_slot=slot, new_slot=monday_slot(req["new_hour"]), **common
        )

    result = await process(
        RequestEnvelope(correlation_id=str(uuid.uuid4()), payload=payload), tools
    )

    assert result.status.value == expected["status"], f"{path.name} status"
    assert result.reason == expected["reason"], f"{path.name} reason"
    if "tools" in expected:
        assert tools.tool_names == expected["tools"], f"{path.name} tool trace"