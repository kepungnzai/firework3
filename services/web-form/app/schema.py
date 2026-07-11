"""Strawberry GraphQL schema for the web-form edge service."""

from __future__ import annotations

from datetime import datetime

import strawberry
from sqlalchemy import select

from apptshared.config import get_settings
from apptshared.db import session_scope
from apptshared.mcpclient import call_tool
from apptshared.models import WorkflowEvent
from apptshared.schemas import Slot

from app import auth, bookings
from app.availability import available_slots as compute_available_slots


@strawberry.type
class ResourceType:
    id: str
    name: str
    email: str
    timezone: str


@strawberry.type
class SlotType:
    start: datetime
    end: datetime


@strawberry.type
class TimelineEvent:
    seq: int
    event_type: str
    from_state: str | None
    to_state: str | None
    actor: str
    tool_name: str | None
    outcome: str
    reason: str | None
    occurred_at: datetime


@strawberry.type
class MutationResult:
    ok: bool
    message: str
    booking_id: str | None = None


@strawberry.type
class Query:
    @strawberry.field
    async def resources(self) -> list[ResourceType]:
        settings = get_settings()
        rows = await call_tool(
            settings.mcp_resource_details_url, "list_resources", {}, settings.mcp_api_key
        )
        return [
            ResourceType(
                id=r["id"], name=r["name"], email=r["email"], timezone=r["timezone"]
            )
            for r in (rows or [])
        ]

    @strawberry.field
    async def available_slots(self, resource: str, day: datetime) -> list[SlotType]:
        slots = await compute_available_slots(resource, day)
        return [SlotType(start=s.start, end=s.end) for s in slots]

    @strawberry.field
    def booking_timeline(self, booking_id: str) -> list[TimelineEvent]:
        """Reconstruct the full lifecycle of a booking from the audit log."""
        for session in session_scope():
            rows = session.execute(
                select(WorkflowEvent)
                .where(WorkflowEvent.booking_id == booking_id)
                .order_by(WorkflowEvent.seq)
            ).scalars()
            return [
                TimelineEvent(
                    seq=e.seq,
                    event_type=e.event_type,
                    from_state=e.from_state,
                    to_state=e.to_state,
                    actor=e.actor,
                    tool_name=e.tool_name,
                    outcome=e.outcome,
                    reason=e.reason,
                    occurred_at=e.occurred_at,
                )
                for e in rows
            ]
        return []


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def start_verification(self, email: str) -> MutationResult:
        await auth.start_verification(email)
        return MutationResult(ok=True, message="Verification email sent.")

    @strawberry.mutation
    def verify_magic_link(self, token: str) -> MutationResult:
        ok = auth.verify_magic_link(token)
        return MutationResult(
            ok=ok, message="Verified." if ok else "Invalid or expired token."
        )

    @strawberry.mutation
    async def request_appointment(
        self, resource: str, email: str, start: datetime, end: datetime
    ) -> MutationResult:
        if not auth.is_verified(email):
            return MutationResult(ok=False, message="Email not verified.")
        try:
            booking_id = await bookings.create_appointment(
                resource, email, Slot(start=start, end=end)
            )
        except bookings.BookingError as exc:
            return MutationResult(ok=False, message=str(exc))
        return MutationResult(
            ok=True, message="Appointment request submitted.", booking_id=booking_id
        )

    @strawberry.mutation
    async def cancel_appointment(
        self, booking_id: str, email: str
    ) -> MutationResult:
        if not auth.is_verified(email):
            return MutationResult(ok=False, message="Email not verified.")
        try:
            await bookings.request_cancellation(booking_id, email)
        except bookings.BookingError as exc:
            return MutationResult(ok=False, message=str(exc))
        return MutationResult(
            ok=True, message="Cancellation submitted.", booking_id=booking_id
        )

    @strawberry.mutation
    async def reschedule_appointment(
        self, booking_id: str, email: str, start: datetime, end: datetime
    ) -> MutationResult:
        if not auth.is_verified(email):
            return MutationResult(ok=False, message="Email not verified.")
        try:
            await bookings.request_reschedule(
                booking_id, email, Slot(start=start, end=end)
            )
        except bookings.BookingError as exc:
            return MutationResult(ok=False, message=str(exc))
        return MutationResult(
            ok=True, message="Reschedule submitted.", booking_id=booking_id
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)
