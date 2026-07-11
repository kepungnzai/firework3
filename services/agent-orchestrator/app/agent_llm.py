"""LLM agent planner — the decision-maker at the center of the orchestrator.

The planner drives an agent loop (see app.agent). Given the pluggable workflow
playbook (app.workflow), the booking request, and the observations gathered so
far, it decides the NEXT action to take from a fixed tool vocabulary. The agent
executes each action behind the firewall (app.firewall: state-machine + email
allow-list) plus the deterministic guardrail admission check, so the model
chooses the workflow while the firewall guarantees safety and auditability.

Action vocabulary (the only things the agent can do):
  get_resource      - look up the resource's calendar/email
  create_event      - book the requested slot          (-> confirmed)
  cancel_event      - cancel the existing booking       (-> cancelled)
  update_event      - move the booking to a new slot    (-> rescheduled)
  offer_reschedule  - offer the patient a new time      (-> reschedule_offered)
  send_email        - notify {patient|resource|guardian} (allow-listed)
  finish            - end the workflow

In FAKE_PROVIDERS mode (tests/local) or when no Foundry endpoint is configured,
a deterministic planner replays the canonical sequence for each request type, so
behaviour is fully reproducible. In production the Foundry model chooses actions
by reading the playbook; if it errors, the planner falls back to the same
canonical sequence so a booking never gets stuck.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from apptshared.config import get_settings
from apptshared.schemas import AppointmentRequest, CancellationRequest

logger = logging.getLogger("agent.planner")


@dataclass
class AgentAction:
    tool: str
    args: dict = field(default_factory=dict)


def _canonical(payload) -> list[AgentAction]:
    """The safe, canonical action sequence for each request type."""
    if isinstance(payload, AppointmentRequest):
        return [
            AgentAction("get_resource"),
            AgentAction("create_event"),
            AgentAction("send_email", {"recipient": "patient", "kind": "confirmation"}),
            AgentAction("send_email", {"recipient": "resource", "kind": "resource_notice"}),
            AgentAction("finish"),
        ]
    if isinstance(payload, CancellationRequest):
        return [
            AgentAction("get_resource"),
            AgentAction("cancel_event"),
            AgentAction("send_email", {"recipient": "patient", "kind": "cancellation"}),
            AgentAction("offer_reschedule"),
            AgentAction("finish"),
        ]
    # RescheduleRequest
    return [
        AgentAction("get_resource"),
        AgentAction("update_event"),
        AgentAction("send_email", {"recipient": "patient", "kind": "reschedule"}),
        AgentAction("finish"),
    ]


class _ScriptedPlanner:
    """Deterministic planner: replays the canonical action sequence for the
    request type. Used in fake mode and as the production fallback."""

    def __init__(self, payload) -> None:
        self._script = _canonical(payload)
        self._i = 0

    def next_action(self, history: list[dict]) -> AgentAction:
        if self._i >= len(self._script):
            return AgentAction("finish")
        action = self._script[self._i]
        self._i += 1
        return action


_VALID_TOOLS = {
    "get_resource",
    "create_event",
    "cancel_event",
    "update_event",
    "offer_reschedule",
    "send_email",
    "finish",
}

_SYSTEM_PROMPT = (
    "You are the orchestrator for an appointment system. Decide the NEXT action "
    "to fulfil the request, following the workflow playbook. Valid tools: "
    "get_resource, create_event, cancel_event, update_event, offer_reschedule, "
    "send_email, finish. For send_email, args are recipient "
    "(patient|resource|guardian) and kind "
    "(confirmation|resource_notice|cancellation|reschedule). Look up the "
    "resource before creating/updating/cancelling events. Emit finish when done. "
    'Respond with ONLY one JSON object: {"tool": "...", "args": {...}}.'
)


def _parse_action(raw: str) -> AgentAction:  # pragma: no cover - live LLM only
    data = json.loads(raw)
    tool = data.get("tool")
    if tool not in _VALID_TOOLS:
        raise ValueError(f"invalid tool: {tool}")
    args = data.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    return AgentAction(tool=tool, args=args)


class _FoundryPlanner:
    """LLM-driven planner: the model reads the workflow playbook, the request,
    and the observations so far, then chooses the next action. Falls back to the
    scripted canonical sequence on any error."""

    def __init__(self, workflow_text: str, payload) -> None:
        self._workflow = workflow_text
        self._payload = payload
        self._fallback = _ScriptedPlanner(payload)

    def next_action(self, history: list[dict]) -> AgentAction:  # pragma: no cover
        try:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            settings = get_settings()
            client = AIProjectClient(
                endpoint=settings.azure_ai_project_endpoint,
                credential=DefaultAzureCredential(),
            )
            completion = client.inference.get_chat_completions_client().complete(
                model=settings.azure_ai_agent_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": self._prompt(history)},
                ],
            )
            return _parse_action(completion.choices[0].message.content or "")
        except Exception as exc:  # noqa: BLE001 - never let planning stall a booking
            logger.warning("planner LLM failed, using canonical step: %s", exc)
            return self._fallback.next_action(history)

    def _prompt(self, history: list[dict]) -> str:
        return (
            f"WORKFLOW PLAYBOOK:\n{self._workflow}\n\n"
            f"REQUEST:\n{self._payload.model_dump_json()}\n\n"
            f"OBSERVATIONS SO FAR:\n{json.dumps(history)}\n\n"
            "Choose the single next action now."
        )


def make_planner(workflow_text: str, payload):
    """Return the planner driving the agent loop.

    Deterministic scripted planner in fake mode or when no Foundry endpoint is
    configured; otherwise the LLM-driven Foundry planner.
    """
    settings = get_settings()
    if settings.fake_providers or not settings.azure_ai_project_endpoint:
        return _ScriptedPlanner(payload)
    return _FoundryPlanner(workflow_text, payload)