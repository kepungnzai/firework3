"""Calendar provider abstraction.

`CalendarProvider` is the interface the MCP tools call. Google is the default
implementation; `FakeCalendarProvider` is an in-memory implementation used for
tests and demos (FAKE_PROVIDERS=true) so no external calls are made.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime


class CalendarProvider(ABC):
    @abstractmethod
    def get_busy_slots(
        self, calendar_id: str, start: datetime, end: datetime
    ) -> list[dict]:
        """Return busy intervals [{"start": iso, "end": iso}] in the window."""

    @abstractmethod
    def create_event(
        self,
        calendar_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        attendees: list[str] | None = None,
    ) -> str:
        """Create an event; return the provider event id."""

    @abstractmethod
    def cancel_event(self, calendar_id: str, event_id: str) -> bool:
        """Delete an event. Returns True on success."""

    @abstractmethod
    def update_event(
        self, calendar_id: str, event_id: str, start: datetime, end: datetime
    ) -> bool:
        """Move an existing event to a new window."""


class FakeCalendarProvider(CalendarProvider):
    """In-memory calendar keyed by calendar_id. Deterministic for tests."""

    def __init__(self) -> None:
        # calendar_id -> {event_id: {"start", "end", "summary"}}
        self._events: dict[str, dict[str, dict]] = {}

    def _cal(self, calendar_id: str) -> dict[str, dict]:
        return self._events.setdefault(calendar_id, {})

    def get_busy_slots(
        self, calendar_id: str, start: datetime, end: datetime
    ) -> list[dict]:
        busy = []
        for ev in self._cal(calendar_id).values():
            if ev["start"] < end and start < ev["end"]:
                busy.append(
                    {"start": ev["start"].isoformat(), "end": ev["end"].isoformat()}
                )
        return sorted(busy, key=lambda b: b["start"])

    def create_event(
        self,
        calendar_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        attendees: list[str] | None = None,
    ) -> str:
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        self._cal(calendar_id)[event_id] = {
            "start": start,
            "end": end,
            "summary": summary,
            "attendees": attendees or [],
        }
        return event_id

    def cancel_event(self, calendar_id: str, event_id: str) -> bool:
        return self._cal(calendar_id).pop(event_id, None) is not None

    def update_event(
        self, calendar_id: str, event_id: str, start: datetime, end: datetime
    ) -> bool:
        ev = self._cal(calendar_id).get(event_id)
        if not ev:
            return False
        ev["start"] = start
        ev["end"] = end
        return True


class GoogleCalendarProvider(CalendarProvider):
    """Google Calendar implementation using the official Python client."""

    def __init__(self, credentials_file: str, token_file: str) -> None:
        self._credentials_file = credentials_file
        self._token_file = token_file
        self._service = None

    def _svc(self):
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(
                self._token_file,
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def get_busy_slots(
        self, calendar_id: str, start: datetime, end: datetime
    ) -> list[dict]:
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": calendar_id}],
        }
        resp = self._svc().freebusy().query(body=body).execute()
        return resp["calendars"][calendar_id].get("busy", [])

    def create_event(
        self,
        calendar_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        attendees: list[str] | None = None,
    ) -> str:
        event = {
            "summary": summary,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
            "attendees": [{"email": a} for a in (attendees or [])],
        }
        created = (
            self._svc().events().insert(calendarId=calendar_id, body=event).execute()
        )
        return created["id"]

    def cancel_event(self, calendar_id: str, event_id: str) -> bool:
        self._svc().events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return True

    def update_event(
        self, calendar_id: str, event_id: str, start: datetime, end: datetime
    ) -> bool:
        body = {
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        self._svc().events().patch(
            calendarId=calendar_id, eventId=event_id, body=body
        ).execute()
        return True


def build_provider() -> CalendarProvider:
    from apptshared.config import get_settings

    settings = get_settings()
    if settings.fake_providers:
        return get_shared_fake()
    return GoogleCalendarProvider(
        settings.google_credentials_file, settings.google_token_file
    )


# A single process-wide fake so busy/create/cancel see the same state.
_SHARED_FAKE: FakeCalendarProvider | None = None


def get_shared_fake() -> FakeCalendarProvider:
    global _SHARED_FAKE
    if _SHARED_FAKE is None:
        _SHARED_FAKE = FakeCalendarProvider()
    return _SHARED_FAKE