"""Test fixtures for the agent orchestrator.

Runs entirely offline: FAKE_PROVIDERS=true, an in-memory SQLite database, and a
`FakeTools` double that dispatches MCP tool calls to in-process fake providers
while preserving the real `Tools.trace` so orchestration can be asserted.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["FAKE_PROVIDERS"] = "true"
os.environ["DATABASE_URL"] = "sqlite://"

import apptshared.db as db  # noqa: E402
from apptshared.config import get_settings  # noqa: E402
from apptshared.models import Base, Booking, Patient, Resource  # noqa: E402
from apptshared.schemas import Slot  # noqa: E402

from app.tools import Tools, ToolCall  # noqa: E402

RESOURCE = {
    "id": "dr-lee",
    "name": "Dr Lee",
    "email": "dr.lee@example.com",
    "calendar_id": "dr-lee@cal",
    "timezone": "Australia/Sydney",
}
HOURS = {
    "timezone": "Australia/Sydney",
    "days": {str(d): {"start": "09:00", "end": "17:00"} for d in range(0, 5)},
}


class FakeTools(Tools):
    """Routes MCP tool calls to in-memory logic; keeps the real trace."""

    def __init__(self) -> None:
        super().__init__()
        self.calendar: dict[str, dict] = {}  # event_id -> {start,end}
        self.busy: list[Slot] = []
        self.emails: list[dict] = []

    async def _call(self, url: str, tool: str, args: dict) -> Any:  # type: ignore[override]
        result = self._dispatch(tool, args)
        self.trace.append(ToolCall(tool=tool, args=args, result=result))
        return result

    def _dispatch(self, tool: str, args: dict) -> Any:
        if tool == "get_resource":
            return RESOURCE
        if tool == "get_opening_hours":
            return HOURS
        if tool == "get_busy_slots":
            start = datetime.fromisoformat(args["start_iso"])
            end = datetime.fromisoformat(args["end_iso"])
            out = []
            for ev in self.calendar.values():
                if ev["start"] < end and start < ev["end"]:
                    out.append(
                        {"start": ev["start"].isoformat(), "end": ev["end"].isoformat()}
                    )
            for b in self.busy:
                if b.start < end and start < b.end:
                    out.append({"start": b.start.isoformat(), "end": b.end.isoformat()})
            return out
        if tool == "create_event":
            eid = f"evt-{uuid.uuid4().hex[:8]}"
            self.calendar[eid] = {
                "start": datetime.fromisoformat(args["start_iso"]),
                "end": datetime.fromisoformat(args["end_iso"]),
            }
            return {"event_id": eid}
        if tool == "cancel_event":
            return {"cancelled": self.calendar.pop(args["event_id"], None) is not None}
        if tool == "update_event":
            ev = self.calendar.get(args["event_id"])
            if ev:
                ev["start"] = datetime.fromisoformat(args["start_iso"])
                ev["end"] = datetime.fromisoformat(args["end_iso"])
            return {"updated": ev is not None}
        if tool == "send_email":
            self.emails.append(args)
            return {"message_id": f"msg-{len(self.emails)}"}
        raise ValueError(f"unknown tool {tool}")


@pytest.fixture(autouse=True)
def fresh_db():
    get_settings.cache_clear()
    # A single shared in-memory connection so every session sees the same DB.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db._engine = engine
    db._SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
    engine.dispose()
    db._engine = None
    db._SessionFactory = None


@pytest.fixture
def seed_resource():
    for session in db.session_scope():
        session.add(
            Resource(
                id=RESOURCE["id"],
                name=RESOURCE["name"],
                email=RESOURCE["email"],
                calendar_id=RESOURCE["calendar_id"],
                timezone=RESOURCE["timezone"],
                active=True,
            )
        )
    return RESOURCE


@pytest.fixture
def verified_patient():
    email = "patient@example.com"
    for session in db.session_scope():
        session.add(
            Patient(
                id=str(uuid.uuid4()),
                email=email,
                verified_at=datetime.now(timezone.utc),
            )
        )
    return email


@pytest.fixture
def unverified_patient():
    email = "anon@example.com"
    for session in db.session_scope():
        session.add(Patient(id=str(uuid.uuid4()), email=email))
    return email


@pytest.fixture
def make_booking(seed_resource, verified_patient):
    """Factory to create a pending booking row for a given slot."""

    def _make(slot: Slot, status: str = "pending", event_id: str | None = None) -> str:
        booking_id = f"bk-{uuid.uuid4().hex[:8]}"
        pid = None
        for session in db.session_scope():
            pid = session.query(Patient).filter_by(email=verified_patient).first().id
            session.add(
                Booking(
                    id=booking_id,
                    patient_id=pid,
                    resource_id=seed_resource["id"],
                    start_utc=slot.start,
                    end_utc=slot.end,
                    status=status,
                    gcal_event_id=event_id,
                    idempotency_key=f"key-{booking_id}",
                )
            )
        return booking_id

    return _make


def monday_slot(hour: int = 9, minute: int = 0, minutes: int = 30) -> Slot:
    """A slot on Mon 2026-07-13 in Sydney time, returned in UTC."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Australia/Sydney")
    start = datetime(2026, 7, 13, hour, minute, tzinfo=tz)
    return Slot(
        start=start.astimezone(timezone.utc),
        end=(start + timedelta(minutes=minutes)).astimezone(timezone.utc),
    )