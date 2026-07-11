"""Append-only audit recorder.

Every guardrail decision, state transition, and tool call is written to
`workflow_events`. `reconstruct_timeline` rebuilds the full ordered lifecycle of
a booking from these events — used by tests and the GraphQL `bookingTimeline`
query.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select

from apptshared.db import session_scope
from apptshared.models import WorkflowEvent
from apptshared.schemas import (
    BookingStatus,
    WorkflowActor,
    WorkflowEventRecord,
    WorkflowOutcome,
)


def _next_seq(session, booking_id: str) -> int:
    current = session.execute(
        select(func.max(WorkflowEvent.seq)).where(
            WorkflowEvent.booking_id == booking_id
        )
    ).scalar()
    return (current or 0) + 1


def record(
    booking_id: str,
    correlation_id: str,
    event_type: str,
    actor: WorkflowActor,
    outcome: WorkflowOutcome,
    from_state: Optional[BookingStatus] = None,
    to_state: Optional[BookingStatus] = None,
    tool_name: Optional[str] = None,
    request_payload: Optional[dict] = None,
    result: Optional[dict] = None,
    reason: Optional[str] = None,
) -> None:
    """Append one immutable audit event."""
    for session in session_scope():
        seq = _next_seq(session, booking_id)
        session.add(
            WorkflowEvent(
                booking_id=booking_id,
                seq=seq,
                correlation_id=correlation_id,
                event_type=event_type,
                from_state=from_state.value if from_state else None,
                to_state=to_state.value if to_state else None,
                actor=actor.value,
                tool_name=tool_name,
                request_payload=request_payload,
                result=result,
                outcome=outcome.value,
                reason=reason,
                occurred_at=datetime.now(timezone.utc),
            )
        )


def reconstruct_timeline(booking_id: str) -> list[WorkflowEventRecord]:
    """Return the ordered lifecycle of a booking from start to end."""
    for session in session_scope():
        rows = session.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.booking_id == booking_id)
            .order_by(WorkflowEvent.seq)
        ).scalars()
        return [
            WorkflowEventRecord(
                booking_id=e.booking_id,
                seq=e.seq,
                correlation_id=e.correlation_id,
                event_type=e.event_type,
                from_state=BookingStatus(e.from_state) if e.from_state else None,
                to_state=BookingStatus(e.to_state) if e.to_state else None,
                actor=WorkflowActor(e.actor),
                tool_name=e.tool_name,
                request_payload=e.request_payload,
                result=e.result,
                outcome=WorkflowOutcome(e.outcome),
                reason=e.reason,
                occurred_at=e.occurred_at,
            )
            for e in rows
        ]
    return []