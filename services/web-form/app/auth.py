"""Magic-link patient verification.

Flow:
1. startVerification(email) -> create a signed token, email a link via MCP email.
2. verifyMagicLink(token)   -> validate token, mark patient verified, return ok.

A patient is "legit" once they have proven control of their email address. The
agent later checks `patients.verified_at` before acting on any request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from apptshared.config import get_settings
from apptshared.db import session_scope
from apptshared.mcpclient import call_tool
from apptshared.models import MagicLinkToken, Patient


def _sign(email: str, nonce: str) -> str:
    settings = get_settings()
    mac = hmac.new(
        settings.magic_link_secret.encode(), f"{email}:{nonce}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{nonce}.{mac}"


async def start_verification(email: str) -> bool:
    settings = get_settings()
    nonce = secrets.token_urlsafe(16)
    token = _sign(email, nonce)
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.magic_link_ttl_minutes
    )

    for session in session_scope():
        session.add(MagicLinkToken(token=token, email=email, expires_at=expires))
        if not session.execute(
            select(Patient).where(Patient.email == email)
        ).scalar_one_or_none():
            session.add(Patient(id=str(uuid.uuid4()), email=email))

    link = f"{settings.public_base_url}/verify?token={token}"
    await call_tool(
        settings.mcp_email_url,
        "send_email",
        {
            "to": email,
            "subject": "Verify your appointment booking",
            "body": f"Click to verify your email and continue booking:\n{link}",
        },
        settings.mcp_api_key,
    )
    return True


def verify_magic_link(token: str) -> bool:
    now = datetime.now(timezone.utc)
    for session in session_scope():
        row = session.get(MagicLinkToken, token)
        if not row or row.used_at is not None or _expired(row.expires_at, now):
            return False
        row.used_at = now
        patient = session.execute(
            select(Patient).where(Patient.email == row.email)
        ).scalar_one_or_none()
        if patient:
            patient.verified_at = now
        return True
    return False


def is_verified(email: str) -> bool:
    for session in session_scope():
        patient = session.execute(
            select(Patient).where(Patient.email == email)
        ).scalar_one_or_none()
        return bool(patient and patient.verified_at is not None)
    return False


def _expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < now
