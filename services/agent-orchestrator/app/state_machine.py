"""Workflow state machine.

This is the source of truth for *which* steps are legal and in *what* order.
The LLM agent decides *how* to satisfy a step (which tools to call); this module
decides whether a transition is permitted and records every transition to the
append-only audit log. Illegal transitions are rejected regardless of what the
model proposes.
"""

from __future__ import annotations

from apptshared.schemas import BookingStatus

# from_state -> set of allowed to_states
_ALLOWED: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.pending: {
        BookingStatus.confirmed,
        BookingStatus.cancelled,
        BookingStatus.rescheduled,
    },
    BookingStatus.confirmed: {
        BookingStatus.cancelled,
        BookingStatus.rescheduled,
    },
    BookingStatus.cancelled: {
        BookingStatus.reschedule_offered,
    },
    BookingStatus.reschedule_offered: {
        BookingStatus.rescheduled,
        BookingStatus.cancelled,
    },
    BookingStatus.rescheduled: {
        BookingStatus.cancelled,
        BookingStatus.rescheduled,
    },
}


class IllegalTransitionError(Exception):
    def __init__(self, frm: BookingStatus, to: BookingStatus) -> None:
        super().__init__(f"Illegal transition {frm.value} -> {to.value}")
        self.frm = frm
        self.to = to


def can_transition(frm: BookingStatus, to: BookingStatus) -> bool:
    return to in _ALLOWED.get(frm, set())


def assert_transition(frm: BookingStatus, to: BookingStatus) -> None:
    if not can_transition(frm, to):
        raise IllegalTransitionError(frm, to)