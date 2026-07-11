"""Self-contained execution harness for evaluation cases.

Each case is run through the *real* agent orchestrator (`app.agent.process`)
against an in-memory SQLite database and deterministic in-memory MCP tool
doubles. That lets us score the final booking status, the ordered tool-call
trace, safety of email recipients, and the composed message text — without any
network, Google, or Azure dependency.

Two modes controlled by `set_mode(use_llm)`:

* scripted (default, ``use_llm=False``): ``FAKE_PROVIDERS=true`` so the agent
  uses the deterministic planner. This validates the harness and provides a
  golden 100% baseline.
* llm (``use_llm=True``): ``FAKE_PROVIDERS=false`` so ``app.agent_llm`` builds
  the Foundry planner and ``app.llm`` composes message text via the model, while
  calendar/email stay deterministic in-memory doubles. The resulting score
  reflects the model's decisions. If no ``AZURE_AI_PROJECT_ENDPOINT`` is
  configured (or the SDK/endpoint errors) the planner safely falls back to the
  canonical sequence, so the harness never crashes.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Settings are read from the environment, so configure the defaults *before* any
# apptshared/app import triggers `get_settings()`.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("FAKE_PROVIDERS", "true")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import apptshared.db as db  # noqa: E402
from apptshared.config import get_settings  # noqa: E402
from apptshared.models import Base, Booking, Patient, Resource  # noqa: E402
from apptshared.schemas import (  # noqa: E402
    AppointmentRequest,
    CancellationRequest,
    RequestEnvelope,
    RescheduleRequest,
    Slot,
)

from app.agent import process  # noqa: E402
from app.tools import ToolCall, Tools  # noqa: E402

# The single resource + opening hours the fake tools serve.
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
PATIENT_EMAIL = "patient@example.com"

# The only addresses the agent is ever allowed to email (patient + resource).
# Any address outside this set is a safety violation (e.g. prompt-injection).
ALLOWED_EMAIL_RECIPIENTS = {PATIENT_EMAIL, RESOURCE["email"]}


def set_mode(use_llm: bool) -> None:
    """Switch the planner/message-composer between scripted and live-LLM modes."""
    os.environ["FAKE_PROVIDERS"] = "false" if use_llm else "true"
    get_settings.cache_clear()


class FakeTools(Tools):
    """Routes MCP tool calls to in-memory logic while keeping the real trace."""

    def __init__(self) -> None:
        super().__init__()
        self.calendar: dict[str, dict] = {}  # event_id -> {start, end}
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
            out: list[dict] = []
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


@dataclass
class CaseRun:
    """The observable outcome of running a single evaluation case."""

    result: Any  # AgentResult
    tool_names: list[str] = field(default_factory=list)
    emails: list[dict] = field(default_factory=list)


def monday_slot(hour: int = 9, minute: int = 0, minutes: int = 30) -> Slot:
    """A slot on Mon 2026-07-13 in Sydney time, returned in UTC."""
    tz = ZoneInfo("Australia/Sydney")
    start = datetime(2026, 7, 13, hour, minute, tzinfo=tz)
    return Slot(
        start=start.astimezone(timezone.utc),
        end=(start + timedelta(minutes=minutes)).astimezone(timezone.utc),
    )


def _reset_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db._engine = engine
    db._SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    return engine


def _seed(setup: dict, slot: Slot) -> str:
    verified = setup.get("patient_verified", True)
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
    for session in db.session_scope():
        session.add(
            Patient(
                id=str(uuid.uuid4()),
                email=PATIENT_EMAIL,
                verified_at=datetime.now(timezone.utc) if verified else None,
            )
        )
    booking_id = f"bk-{uuid.uuid4().hex[:8]}"
    for session in db.session_scope():
        pid = session.query(Patient).filter_by(email=PATIENT_EMAIL).first().id
        session.add(
            Booking(
                id=booking_id,
                patient_id=pid,
                resource_id=RESOURCE["id"],
                start_utc=slot.start,
                end_utc=slot.end,
                status=setup.get("booking_status", "pending"),
                gcal_event_id=setup.get("event_id"),
                idempotency_key=f"key-{booking_id}",
            )
        )
    return booking_id


def _build_payload(req: dict, booking_id: str, slot: Slot):
    common = dict(
        booking_id=booking_id,
        resource=req["resource"],
        patient_email=PATIENT_EMAIL,
        idempotency_key=f"key-{uuid.uuid4().hex[:8]}",
    )
    kind = req["type"]
    if kind == "appointment":
        return AppointmentRequest(slot=slot, **common)
    if kind == "cancellation":
        return CancellationRequest(slot=slot, **common)
    return RescheduleRequest(
        old_slot=slot, new_slot=monday_slot(req["new_hour"]), **common
    )


async def run_case(spec: dict) -> CaseRun:
    """Execute one evaluation case end-to-end and capture the outcome."""
    engine = _reset_db()
    try:
        req = spec["request"]
        setup = spec.get("setup", {})
        slot = monday_slot(req["hour"])
        booking_id = _seed(setup, slot)

        tools = FakeTools()
        for ev in setup.get("calendar", []):
            s = monday_slot(ev["hour"])
            tools.calendar[ev["event_id"]] = {"start": s.start, "end": s.end}
        tools.busy = [monday_slot(h) for h in setup.get("busy", [])]

        payload = _build_payload(req, booking_id, slot)
        envelope = RequestEnvelope(correlation_id=str(uuid.uuid4()), payload=payload)
        result = await process(envelope, tools)
        return CaseRun(
            result=result,
            tool_names=list(tools.tool_names),
            emails=list(tools.emails),
        )
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
        db._engine = None
        db._SessionFactory = None
