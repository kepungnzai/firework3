"""Pluggable workflow playbook.

A *workflow* is a plain-text 'playbook' describing what the agent should do for a
booking, on top of the mandatory deterministic core (validate -> create event ->
confirm -> email). It is where policy-specific extra steps live, e.g. "notify a
minor patient's guardian".

Today the playbook is a single hard-coded default (a 'standard temporary
workflow'). `load_workflow` is the seam where this becomes dynamic later —
loaded per resource from the DB, a file, or a RAG retrieval step — without
touching the agent or the planner.

Safety: the LLM planner (app.planner) may only turn this text into *additional
notification* steps drawn from a fixed allow-list. The deterministic guardrail
and state machine still own every calendar mutation and status transition.
"""

from __future__ import annotations

DEFAULT_WORKFLOW_TEXT = """\
# Appointment workflow (standard, pluggable)

You orchestrate one booking request at a time. It has already passed the
deterministic guardrail (patient verified, slot within opening hours, slot free).
Choose actions from the tool vocabulary to fulfil it, then finish.

New appointment:
1. get_resource to load the resource's calendar and email.
2. create_event to book the requested slot (moves the booking to 'confirmed').
3. send_email to the patient (kind=confirmation).
4. send_email to the resource (kind=resource_notice).
5. finish.

Cancellation:
1. get_resource.
2. cancel_event to release the existing booking (moves to 'cancelled').
3. send_email to the patient (kind=cancellation).
4. offer_reschedule to invite the patient to pick a new time.
5. finish.

Reschedule:
1. get_resource.
2. update_event to move the booking to the new slot (moves to 'rescheduled').
3. send_email to the patient (kind=reschedule).
4. finish.

Policy notes (pluggable):
- If the appointment is for a minor, also send additional preparation
  instructions to the patient's guardian.

Never invent calendar operations beyond the tools provided. The state machine
rejects any illegal transition regardless of what you request.
"""


def load_workflow(resource: str | None = None) -> str:
    """Return the workflow playbook text for a resource.

    Currently returns the standard hard-coded playbook regardless of resource.
    This is the extension point for dynamic / pluggable workflows: per-resource
    config, a database row, a file on disk, or a RAG retrieval step can be
    resolved here later without changing callers.
    """
    return DEFAULT_WORKFLOW_TEXT