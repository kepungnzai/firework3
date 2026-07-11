"""MCP tool wrappers with a captured call trace.

`Tools` wraps the remote MCP servers (resource-details, calendar, email). Every
invocation is appended to `self.trace` as (tool_name, args, result). Tests assert
on this ordered trace to verify the agent performed the right next steps — the
key testability enabler for orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from apptshared.config import get_settings
from apptshared.mcpclient import call_tool
from apptshared.schemas import Slot


@dataclass
class ToolCall:
    tool: str
    args: dict
    result: Any = None


@dataclass
class Tools:
    trace: list[ToolCall] = field(default_factory=list)

    async def _call(self, url: str, tool: str, args: dict) -> Any:
        settings = get_settings()
        result = await call_tool(url, tool, args, settings.mcp_api_key)
        self.trace.append(ToolCall(tool=tool, args=args, result=result))
        return result

    @property
    def tool_names(self) -> list[str]:
        return [c.tool for c in self.trace]

    # --- resource-details ---
    async def get_resource(self, resource: str) -> dict:
        return await self._call(
            get_settings().mcp_resource_details_url, "get_resource", {"resource": resource}
        )

    async def get_opening_hours(self, resource: str) -> dict:
        return await self._call(
            get_settings().mcp_resource_details_url,
            "get_opening_hours",
            {"resource": resource},
        )

    # --- calendar ---
    async def get_busy_slots(self, calendar_id: str, start: datetime, end: datetime) -> list[dict]:
        return await self._call(
            get_settings().mcp_calendar_url,
            "get_busy_slots",
            {
                "calendar_id": calendar_id,
                "start_iso": start.isoformat(),
                "end_iso": end.isoformat(),
            },
        )

    async def create_event(
        self, calendar_id: str, summary: str, slot: Slot, attendees: list[str]
    ) -> dict:
        return await self._call(
            get_settings().mcp_calendar_url,
            "create_event",
            {
                "calendar_id": calendar_id,
                "summary": summary,
                "start_iso": slot.start.isoformat(),
                "end_iso": slot.end.isoformat(),
                "attendees": attendees,
            },
        )

    async def cancel_event(self, calendar_id: str, event_id: str) -> dict:
        return await self._call(
            get_settings().mcp_calendar_url,
            "cancel_event",
            {"calendar_id": calendar_id, "event_id": event_id},
        )

    async def update_event(self, calendar_id: str, event_id: str, slot: Slot) -> dict:
        return await self._call(
            get_settings().mcp_calendar_url,
            "update_event",
            {
                "calendar_id": calendar_id,
                "event_id": event_id,
                "start_iso": slot.start.isoformat(),
                "end_iso": slot.end.isoformat(),
            },
        )

    # --- email ---
    async def send_email(self, to: str, subject: str, body: str) -> dict:
        return await self._call(
            get_settings().mcp_email_url,
            "send_email",
            {"to": to, "subject": subject, "body": body},
        )