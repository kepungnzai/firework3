"""Seed baseline data: two resources and org opening hours 09:00-17:00 Mon-Fri.

Idempotent: safe to run repeatedly.
"""

from __future__ import annotations

from datetime import time

from sqlalchemy import select

from apptshared.db import session_scope
from apptshared.models import OpeningHours, Resource

RESOURCES = [
    Resource(
        id="dr-lee",
        name="Dr Lee",
        email="dr.lee@example.com",
        calendar_id="dr-lee@group.calendar.google.com",
        timezone="Australia/Sydney",
        active=True,
    ),
    Resource(
        id="dr-patel",
        name="Dr Patel",
        email="dr.patel@example.com",
        calendar_id="dr-patel@group.calendar.google.com",
        timezone="Australia/Sydney",
        active=True,
    ),
]


def run() -> None:
    for session in session_scope():
        for res in RESOURCES:
            exists = session.get(Resource, res.id)
            if not exists:
                session.add(res)

        # Org opening hours Mon(0)-Fri(4) 09:00-17:00
        has_hours = session.execute(
            select(OpeningHours).where(OpeningHours.scope == "org")
        ).first()
        if not has_hours:
            for dow in range(0, 5):
                session.add(
                    OpeningHours(
                        scope="org",
                        resource_id=None,
                        day_of_week=dow,
                        start_time=time(9, 0),
                        end_time=time(17, 0),
                    )
                )


if __name__ == "__main__":
    run()
    print("Seed complete.")