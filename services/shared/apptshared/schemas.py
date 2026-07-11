"""Pydantic contracts shared across the web-form service, the agent
orchestrator, and the MCP tools.

These types are the single source of truth for:
- the queue message envelope published by the web-form service,
- the per-type request payloads (appointment / cancellation / reschedule),
- the JSON result the agent returns,
- the append-only workflow audit event.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RequestType(str, Enum):
    appointment = "appointment"
    cancellation = "cancellation"
    reschedule = "reschedule"


class BookingStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    reschedule_offered = "reschedule_offered"
    rescheduled = "rescheduled"


class WorkflowActor(str, Enum):
    guardrail = "guardrail"
    agent = "agent"
    tool = "tool"
    system = "system"


class WorkflowOutcome(str, Enum):
    ok = "ok"
    rejected = "rejected"
    error = "error"


class Slot(BaseModel):
    """A timezone-aware time window. Times are stored/compared in UTC."""

    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime

    def overlaps(self, other: "Slot") -> bool:
        return self.start < other.end and other.start < self.end


class _BaseRequest(BaseModel):
    """Fields common to every request type."""

    booking_id: str = Field(..., description="System-of-record booking id (from DB)")
    resource: str = Field(..., description="Resource name, e.g. 'Dr Lee'")
    patient_email: str
    idempotency_key: str


class AppointmentRequest(_BaseRequest):
    type: Literal[RequestType.appointment] = RequestType.appointment
    slot: Slot


class CancellationRequest(_BaseRequest):
    type: Literal[RequestType.cancellation] = RequestType.cancellation
    slot: Slot


class RescheduleRequest(_BaseRequest):
    type: Literal[RequestType.reschedule] = RequestType.reschedule
    old_slot: Slot
    new_slot: Slot


class RequestEnvelope(BaseModel):
    """Discriminated union delivered on the queue to the agent orchestrator."""

    model_config = ConfigDict(use_enum_values=False)

    correlation_id: str
    payload: AppointmentRequest | CancellationRequest | RescheduleRequest = Field(
        ..., discriminator="type"
    )


class AgentResult(BaseModel):
    """JSON returned by the agent after processing a request."""

    type: RequestType
    resource: str
    booking_id: str
    status: BookingStatus
    slot: Optional[Slot] = None
    reason: Optional[str] = Field(
        default=None, description="Populated when a request is rejected"
    )


class WorkflowEventRecord(BaseModel):
    """A single append-only audit event. Ordering per booking is by `seq`."""

    booking_id: str
    seq: int
    correlation_id: str
    event_type: str
    from_state: Optional[BookingStatus] = None
    to_state: Optional[BookingStatus] = None
    actor: WorkflowActor
    tool_name: Optional[str] = None
    request_payload: Optional[dict] = None
    result: Optional[dict] = None
    outcome: WorkflowOutcome
    reason: Optional[str] = None
    occurred_at: datetime
