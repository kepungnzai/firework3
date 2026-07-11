"""State machine unit tests — legal vs illegal transitions."""

from __future__ import annotations

import pytest

from apptshared.schemas import BookingStatus as S

from app.state_machine import (
    IllegalTransitionError,
    assert_transition,
    can_transition,
)


@pytest.mark.parametrize(
    "frm,to",
    [
        (S.pending, S.confirmed),
        (S.pending, S.cancelled),
        (S.confirmed, S.cancelled),
        (S.confirmed, S.rescheduled),
        (S.cancelled, S.reschedule_offered),
        (S.reschedule_offered, S.rescheduled),
    ],
)
def test_legal_transitions(frm, to):
    assert can_transition(frm, to)
    assert_transition(frm, to)  # does not raise


@pytest.mark.parametrize(
    "frm,to",
    [
        (S.cancelled, S.confirmed),
        (S.confirmed, S.pending),
        (S.pending, S.reschedule_offered),
        (S.reschedule_offered, S.confirmed),
    ],
)
def test_illegal_transitions(frm, to):
    assert not can_transition(frm, to)
    with pytest.raises(IllegalTransitionError):
        assert_transition(frm, to)