"""Queue consumer entrypoint for the agent orchestrator.

Pulls request envelopes off the queue (Azure Service Bus in prod, file-backed
queue locally) and runs each through the agent workflow.
"""

from __future__ import annotations

import asyncio
import logging

from apptshared.config import get_settings
from apptshared.queue import build_queue
from apptshared.schemas import RequestEnvelope

from app.agent import process

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger("agent.consumer")


def _handle(envelope: RequestEnvelope) -> None:
    result = asyncio.run(process(envelope))
    logger.info(
        "processed booking=%s type=%s status=%s reason=%s",
        result.booking_id,
        result.type.value,
        result.status.value,
        result.reason,
    )


def main() -> None:
    logger.info("agent orchestrator consuming from queue...")
    queue = build_queue()
    logger.info(f"Using queue backend: {type(queue).__name__}")
    queue.consume_forever(_handle)


if __name__ == "__main__":
    main()