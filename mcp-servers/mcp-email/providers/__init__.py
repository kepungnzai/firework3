"""Email provider abstraction.

`EmailProvider` is the interface the MCP tool calls. Gmail is the default;
`FakeEmailProvider` captures messages in memory for tests/demos so sent mail
can be asserted without hitting Gmail.
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.mime.text import MIMEText


@dataclass
class CapturedEmail:
    to: str
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)


class EmailProvider(ABC):
    @abstractmethod
    def send_email(
        self, to: str, subject: str, body: str, cc: list[str] | None = None
    ) -> str:
        """Send an email; return a provider message id."""


class FakeEmailProvider(EmailProvider):
    """In-memory outbox. Inspect `.outbox` in tests."""

    def __init__(self) -> None:
        self.outbox: list[CapturedEmail] = []

    def send_email(
        self, to: str, subject: str, body: str, cc: list[str] | None = None
    ) -> str:
        self.outbox.append(CapturedEmail(to=to, subject=subject, body=body, cc=cc or []))
        return f"fake-msg-{len(self.outbox)}"


class GmailProvider(EmailProvider):
    """Gmail implementation using the Gmail API."""

    def __init__(self, credentials_file: str, token_file: str, sender: str) -> None:
        self._credentials_file = credentials_file
        self._token_file = token_file
        self._sender = sender
        self._service = None

    def _svc(self):
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(
                self._token_file,
                scopes=["https://www.googleapis.com/auth/gmail.send"],
            )
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def send_email(
        self, to: str, subject: str, body: str, cc: list[str] | None = None
    ) -> str:
        message = MIMEText(body)
        message["to"] = to
        message["from"] = self._sender
        message["subject"] = subject
        if cc:
            message["cc"] = ",".join(cc)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = (
            self._svc()
            .users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return sent["id"]


_SHARED_FAKE: FakeEmailProvider | None = None


def get_shared_fake() -> FakeEmailProvider:
    global _SHARED_FAKE
    if _SHARED_FAKE is None:
        _SHARED_FAKE = FakeEmailProvider()
    return _SHARED_FAKE


def build_provider() -> EmailProvider:
    from apptshared.config import get_settings

    settings = get_settings()
    if settings.fake_providers:
        return get_shared_fake()
    return GmailProvider(
        settings.google_credentials_file,
        settings.google_token_file,
        settings.gmail_sender,
    )