"""LLM adapter for composing patient-facing message text.

When FAKE_PROVIDERS=true (tests/local) these return deterministic strings so the
tool-call trace and audit log stay reproducible. When running against real
providers this is where an Azure AI Foundry agent/model call would generate a
friendlier natural-language message. The control flow never depends on the LLM.
"""

from __future__ import annotations

from apptshared.config import get_settings
from apptshared.schemas import Slot


def _fake() -> bool:
    return get_settings().fake_providers


def confirmation_text(resource: str, slot: Slot) -> str:
    base = (
        f"Your appointment with {resource} is confirmed for "
        f"{slot.start.isoformat()} to {slot.end.isoformat()}."
    )
    if _fake():
        return base
    return _foundry_compose("confirmation", resource, slot, base)


def reschedule_text(resource: str, slot: Slot) -> str:
    base = (
        f"Your appointment with {resource} has been rescheduled to "
        f"{slot.start.isoformat()} to {slot.end.isoformat()}."
    )
    if _fake():
        return base
    return _foundry_compose("reschedule", resource, slot, base)


def _foundry_compose(kind: str, resource: str, slot: Slot, fallback: str) -> str:
    """Compose message text via Azure AI Foundry. Falls back to the deterministic
    text if the Foundry SDK/endpoint is unavailable."""
    settings = get_settings()
    if not settings.azure_ai_project_endpoint:
        return fallback
    try:  # pragma: no cover - exercised only with a live Foundry endpoint
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        client = AIProjectClient(
            endpoint=settings.azure_ai_project_endpoint,
            credential=DefaultAzureCredential(),
        )
        prompt = (
            f"Write a short, friendly {kind} message for an appointment with "
            f"{resource} from {slot.start.isoformat()} to {slot.end.isoformat()}."
        )
        completion = client.inference.get_chat_completions_client().complete(
            model=settings.azure_ai_agent_model,
            messages=[{"role": "user", "content": prompt}],
        )
        return completion.choices[0].message.content or fallback
    except Exception:
        return fallback