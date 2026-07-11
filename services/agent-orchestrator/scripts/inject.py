"""Inject-a-message CLI — the fastest way to test the agent end-to-end.

Publishes a request envelope straight onto the queue (no form/browser needed),
then optionally runs the agent once and prints the resulting tool-call trace and
audit timeline so you can see exactly which next-steps the agent took.

Examples:
    python -m scripts.inject appointment --resource "Dr Lee" \
        --email you@example.com --start 2026-07-13T09:00:00+10:00 --run
    python -m scripts.inject cancellation --booking bk-123 --email you@example.com --run
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime, timedelta

from apptshared.queue import build_queue
from apptshared.schemas import (
    AppointmentRequest,
    CancellationRequest,
    RequestEnvelope,
    RescheduleRequest,
    Slot,
)


def _slot(start_iso: str, minutes: int) -> Slot:
    start = datetime.fromisoformat(start_iso)
    return Slot(start=start, end=start + timedelta(minutes=minutes))


def build_envelope(args: argparse.Namespace) -> RequestEnvelope:
    corr = str(uuid.uuid4())
    booking_id = args.booking or f"bk-{uuid.uuid4().hex[:10]}"
    if args.command == "appointment":
        slot = _slot(args.start, args.minutes)
        payload = AppointmentRequest(
            booking_id=booking_id,
            resource=args.resource,
            patient_email=args.email,
            idempotency_key=f"appt-{booking_id}",
            slot=slot,
        )
    elif args.command == "cancellation":
        slot = _slot(args.start, args.minutes) if args.start else _slot(
            "2026-07-13T09:00:00+10:00", args.minutes
        )
        payload = CancellationRequest(
            booking_id=booking_id,
            resource=args.resource,
            patient_email=args.email,
            idempotency_key=f"cancel-{booking_id}",
            slot=slot,
        )
    else:  # reschedule
        payload = RescheduleRequest(
            booking_id=booking_id,
            resource=args.resource,
            patient_email=args.email,
            idempotency_key=f"resched-{booking_id}",
            old_slot=_slot(args.start, args.minutes),
            new_slot=_slot(args.new_start, args.minutes),
        )
    return RequestEnvelope(correlation_id=corr, payload=payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject an appointment request")
    parser.add_argument(
        "command", choices=["appointment", "cancellation", "reschedule"]
    )
    parser.add_argument("--resource", default="Dr Lee")
    parser.add_argument("--email", required=True)
    parser.add_argument("--booking")
    parser.add_argument("--start")
    parser.add_argument("--new-start", dest="new_start")
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument(
        "--run", action="store_true", help="Run the agent once and print the trace"
    )
    args = parser.parse_args()

    envelope = build_envelope(args)
    build_queue().publish(envelope)
    print(f"Published {args.command} for booking {envelope.payload.booking_id}")

    if args.run:
        from app.agent import process
        from app.audit import reconstruct_timeline
        from app.tools import Tools

        tools = Tools()
        result = asyncio.run(process(envelope, tools))
        print("\nAgent result:")
        print(result.model_dump_json(indent=2))
        print("\nTool-call trace:")
        for call in tools.trace:
            print(f"  - {call.tool}({', '.join(call.args.keys())})")
        print("\nAudit timeline:")
        for ev in reconstruct_timeline(envelope.payload.booking_id):
            print(
                f"  {ev.seq}. {ev.event_type} [{ev.actor.value}] "
                f"{ev.from_state or '-'} -> {ev.to_state or '-'} ({ev.outcome.value})"
            )


if __name__ == "__main__":
    main()