"""Agent orchestration ('Agent 2' role).

The LLM agent is at the center: an agent loop asks the planner (app.agent_llm)
for the next action, executes it, feeds the observation back, and repeats until
the model finishes. The planner reads the pluggable workflow playbook
(app.workflow) and decides *what* to do; the firewall (app.firewall) + the
guardrail admission check enforce *what is allowed* — legal state transitions and
an email recipient allow-list — so every action stays safe and auditable.

In FAKE_PROVIDERS mode (tests/local) the planner deterministically replays the
canonical action sequence, so the workflow is fully reproducible.

Action vocabulary: get_resource, create_event, cancel_event, update_event,
offer_reschedule, send_email, finish.
"""

from __future__ import annotations

from dataclasses import dataclass

from apptshared.schemas import (
    AgentResult,
    AppointmentRequest,
    BookingStatus,
    RequestEnvelope,
    WorkflowActor,
    WorkflowOutcome,
)

from app import agent_llm, audit, firewall, guardrail, llm, repository, workflow
from app.state_machine import IllegalTransitionError
from app.tools import Tools


async def process(envelope: RequestEnvelope, tools: Tools | None = None) -> AgentResult:
    tools = tools or Tools()
    payload = envelope.payload
    corr = envelope.correlation_id
    booking_id = payload.booking_id

    # Idempotency: skip if already in a terminal state for this key.
    if repository.already_processed(payload.idempotency_key):
        audit.record(
            booking_id, corr, "duplicate_skipped", WorkflowActor.system,
            WorkflowOutcome.ok, reason="idempotent_duplicate",
        )
        return _result(payload, repository.get_status(booking_id) or BookingStatus.confirmed)

    # Deterministic guardrail gate.
    verdict = await guardrail.validate(payload, tools)
    if not verdict.ok:
        return await _reject(payload, corr, tools, verdict.reason or "rejected")

    audit.record(
        booking_id, corr, "guardrail_passed", WorkflowActor.guardrail, WorkflowOutcome.ok
    )

    # LLM-driven agent loop: the planner decides each next action; the firewall
    # (guardrail admission above + state-machine transition checks below) keeps
    # every action safe and auditable.
    return await _run_agent_loop(payload, corr, tools)


_MAX_STEPS = 12


@dataclass
class _LoopState:
    resource: dict | None = None
    status: BookingStatus | None = None


async def _run_agent_loop(payload, corr: str, tools: Tools) -> AgentResult:
    """Ask the planner for the next action, execute it behind the firewall, feed
    the observation back, and repeat until the model finishes. The model decides
    the workflow; the firewall enforces legal transitions and the recipient
    allow-list."""
    workflow_text = workflow.load_workflow(payload.resource)
    plan = agent_llm.make_planner(workflow_text, payload)
    state = _LoopState()
    history: list[dict] = []

    for _ in range(_MAX_STEPS):
        action = plan.next_action(history)
        if action.tool == "finish":
            break
        try:
            observation = await _execute(action, payload, corr, tools, state)
        except IllegalTransitionError as exc:
            return await _reject(payload, corr, tools, str(exc))
        history.append({"action": action.tool, "observation": observation})

    final = state.status or repository.get_status(payload.booking_id) or BookingStatus.confirmed
    return _result(payload, final)


async def _execute(action, payload, corr: str, tools: Tools, state: _LoopState) -> dict:
    tool = action.tool
    if tool == "get_resource":
        state.resource = await tools.get_resource(payload.resource)
        return {"resource": state.resource}
    if tool == "create_event":
        return await _exec_create_event(payload, corr, tools, state)
    if tool == "cancel_event":
        return await _exec_cancel_event(payload, corr, tools, state)
    if tool == "update_event":
        return await _exec_update_event(payload, corr, tools, state)
    if tool == "offer_reschedule":
        return _exec_offer_reschedule(payload, corr, state)
    if tool == "send_email":
        return await _exec_send_email(action.args, payload, tools, state)
    raise ValueError(f"Unknown agent action: {tool}")


async def _resource(payload, tools: Tools, state: _LoopState) -> dict:
    if state.resource is None:
        state.resource = await tools.get_resource(payload.resource)
    return state.resource


async def _exec_create_event(payload, corr: str, tools: Tools, state: _LoopState) -> dict:
    booking_id = payload.booking_id
    resource = await _resource(payload, tools, state)
    frm = firewall.check_transition(booking_id, BookingStatus.confirmed, BookingStatus.pending)
    created = await tools.create_event(
        resource["calendar_id"],
        f"Appointment: {payload.resource}",
        payload.slot,
        [payload.patient_email, resource["email"]],
    )
    repository.set_event_id(booking_id, created.get("event_id"))
    repository.set_status(booking_id, BookingStatus.confirmed)
    state.status = BookingStatus.confirmed
    audit.record(
        booking_id, corr, "appointment_confirmed", WorkflowActor.agent,
        WorkflowOutcome.ok, from_state=frm, to_state=BookingStatus.confirmed,
        tool_name="create_event", result=created,
    )
    return {"event_id": created.get("event_id"), "status": "confirmed"}


async def _exec_cancel_event(payload, corr: str, tools: Tools, state: _LoopState) -> dict:
    booking_id = payload.booking_id
    resource = await _resource(payload, tools, state)
    frm = firewall.check_transition(booking_id, BookingStatus.cancelled, BookingStatus.confirmed)
    event_id = repository.get_calendar_event_id(booking_id)
    if event_id:
        await tools.cancel_event(resource["calendar_id"], event_id)
        repository.set_event_id(booking_id, None)
    repository.set_status(booking_id, BookingStatus.cancelled)
    state.status = BookingStatus.cancelled
    audit.record(
        booking_id, corr, "appointment_cancelled", WorkflowActor.agent,
        WorkflowOutcome.ok, from_state=frm, to_state=BookingStatus.cancelled,
        tool_name="cancel_event",
    )
    return {"status": "cancelled"}


def _exec_offer_reschedule(payload, corr: str, state: _LoopState) -> dict:
    booking_id = payload.booking_id
    frm = firewall.check_transition(
        booking_id, BookingStatus.reschedule_offered, BookingStatus.cancelled
    )
    repository.set_status(booking_id, BookingStatus.reschedule_offered)
    state.status = BookingStatus.reschedule_offered
    audit.record(
        booking_id, corr, "reschedule_offered", WorkflowActor.agent, WorkflowOutcome.ok,
        from_state=frm, to_state=BookingStatus.reschedule_offered,
    )
    return {"status": "reschedule_offered"}


async def _exec_update_event(payload, corr: str, tools: Tools, state: _LoopState) -> dict:
    booking_id = payload.booking_id
    resource = await _resource(payload, tools, state)
    frm = firewall.check_transition(booking_id, BookingStatus.rescheduled, BookingStatus.confirmed)
    event_id = repository.get_calendar_event_id(booking_id)
    if event_id:
        await tools.update_event(resource["calendar_id"], event_id, payload.new_slot)
    else:
        created = await tools.create_event(
            resource["calendar_id"],
            f"Appointment: {payload.resource}",
            payload.new_slot,
            [payload.patient_email, resource["email"]],
        )
        repository.set_event_id(booking_id, created.get("event_id"))
    repository.set_slot(booking_id, payload.new_slot)
    repository.set_status(booking_id, BookingStatus.rescheduled)
    state.status = BookingStatus.rescheduled
    audit.record(
        booking_id, corr, "appointment_rescheduled", WorkflowActor.agent,
        WorkflowOutcome.ok, from_state=frm, to_state=BookingStatus.rescheduled,
        tool_name="update_event",
    )
    return {"status": "rescheduled"}


async def _exec_send_email(args: dict, payload, tools: Tools, state: _LoopState) -> dict:
    recipient = args.get("recipient", "patient")
    kind = args.get("kind", "confirmation")
    to = firewall.resolve_recipient(recipient, payload, state.resource)
    if not to:
        return {"skipped": f"no_address_for_{recipient}"}
    subject, body = _render_email(kind, payload)
    await tools.send_email(to, subject, body)
    return {"sent_to": recipient}


def _render_email(kind: str, payload) -> tuple[str, str]:
    if kind == "confirmation":
        return "Appointment confirmed", llm.confirmation_text(payload.resource, payload.slot)
    if kind == "resource_notice":
        return (
            "New appointment booked",
            f"New booking with {payload.patient_email} at {payload.slot.start.isoformat()}.",
        )
    if kind == "cancellation":
        return (
            "Appointment cancelled",
            "Your appointment has been cancelled. Would you like to reschedule?",
        )
    if kind == "reschedule":
        return "Appointment rescheduled", llm.reschedule_text(payload.resource, payload.new_slot)
    return "Appointment update", "There is an update to your appointment."


async def _reject(payload, corr: str, tools: Tools, reason: str) -> AgentResult:
    booking_id = payload.booking_id
    frm = repository.get_status(booking_id)
    # Release the pending hold on a rejected new appointment.
    if isinstance(payload, AppointmentRequest) and frm == BookingStatus.pending:
        repository.set_status(booking_id, BookingStatus.cancelled)
    audit.record(
        booking_id, corr, "request_rejected", WorkflowActor.guardrail,
        WorkflowOutcome.rejected, from_state=frm, reason=reason,
    )
    await tools.send_email(
        payload.patient_email,
        "We could not complete your request",
        f"Your request could not be completed: {reason}.",
    )
    slot = getattr(payload, "slot", None) or getattr(payload, "new_slot", None)
    return AgentResult(
        type=payload.type,
        resource=payload.resource,
        booking_id=booking_id,
        status=repository.get_status(booking_id) or BookingStatus.cancelled,
        slot=slot,
        reason=reason,
    )


def _result(payload, status: BookingStatus) -> AgentResult:
    slot = getattr(payload, "slot", None) or getattr(payload, "new_slot", None)
    return AgentResult(
        type=payload.type,
        resource=payload.resource,
        booking_id=payload.booking_id,
        status=status,
        slot=slot,
    )