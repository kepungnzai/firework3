"""Policy firewall around every action the agent proposes.

The LLM agent (app.agent + app.agent_llm) decides *what* to do; this module is
the boundary that decides whether each action is *allowed*:

- `check_transition` enforces the workflow state machine on any status change,
  raising `IllegalTransitionError` for anything illegal regardless of what the
  model asked for.
- `resolve_recipient` maps an allow-listed role to a *trusted* address. Email
  addresses are never taken from LLM output, so a hallucinated or injected
  instruction can never exfiltrate mail to an arbitrary recipient.

Combined with the deterministic guardrail admission check in app.agent, this
keeps the model at the center of decision-making while guaranteeing safety and
auditability.
"""

from __future__ import annotations

from apptshared.schemas import BookingStatus

from app import repository
from app.state_machine import assert_transition


def check_transition(
    booking_id: str, to: BookingStatus, default: BookingStatus
) -> BookingStatus:
    """Validate a proposed status change against the state machine.

    Returns the current (from) state so callers can record it in the audit log.
    Raises IllegalTransitionError if the transition is not permitted.
    """
    frm = repository.get_status(booking_id) or default
    assert_transition(frm, to)
    return frm


def resolve_recipient(role: str, payload, resource: dict | None) -> str | None:
    """Map an allow-listed recipient role to a trusted email address.

    Guardian contact is not yet stored, so it resolves to None (the step is
    skipped) until that data source is added.
    """
    if role == "patient":
        return payload.patient_email
    if role == "resource":
        return resource.get("email") if resource else None
    return None