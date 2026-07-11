"""Message queue abstraction between the web-form service (publisher) and the
agent orchestrator (consumer).

Two backends:
- Azure Service Bus (production) when a connection string is configured.
- A local file-based queue (a directory of JSON messages) for local dev, tests,
  and the inject-a-message CLI. It works across processes via a shared volume.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Callable

from apptshared.config import get_settings
from apptshared.schemas import RequestEnvelope

_LOCAL_QUEUE_DIR = Path(os.getenv("LOCAL_QUEUE_DIR", ".localqueue"))


class QueueBackend:
    def publish(self, envelope: RequestEnvelope) -> None:  # pragma: no cover
        raise NotImplementedError

    def consume_forever(self, handler: Callable[[RequestEnvelope], None]) -> None:  # pragma: no cover
        raise NotImplementedError


class FileQueue(QueueBackend):
    """Directory-backed queue. Messages are JSON files; processed files are
    moved to a `done/` subfolder so the audit trail is preserved."""

    def __init__(self, directory: Path = _LOCAL_QUEUE_DIR) -> None:
        self.dir = directory
        self.done = directory / "done"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.done.mkdir(parents=True, exist_ok=True)

    def publish(self, envelope: RequestEnvelope) -> None:
        name = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.json"
        path = self.dir / name
        path.write_text(envelope.model_dump_json(), encoding="utf-8")

    def _pending(self) -> list[Path]:
        return sorted(p for p in self.dir.glob("*.json") if p.is_file())

    def consume_once(self, handler: Callable[[RequestEnvelope], None]) -> int:
        processed = 0
        for path in self._pending():
            data = json.loads(path.read_text(encoding="utf-8"))
            envelope = RequestEnvelope.model_validate(data)
            handler(envelope)
            path.rename(self.done / path.name)
            processed += 1
        return processed

    def consume_forever(self, handler: Callable[[RequestEnvelope], None]) -> None:
        while True:
            if self.consume_once(handler) == 0:
                time.sleep(1.0)


class ServiceBusQueue(QueueBackend):
    """Azure Service Bus backend."""

    def __init__(self, connection_string: str, queue_name: str) -> None:
        self._conn = connection_string
        self._queue = queue_name

    def publish(self, envelope: RequestEnvelope) -> None:
        from azure.servicebus import ServiceBusClient, ServiceBusMessage

        with ServiceBusClient.from_connection_string(self._conn) as client:
            sender = client.get_queue_sender(self._queue)
            with sender:
                sender.send_messages(ServiceBusMessage(envelope.model_dump_json()))

    def consume_forever(self, handler: Callable[[RequestEnvelope], None]) -> None:
        from azure.servicebus import ServiceBusClient

        with ServiceBusClient.from_connection_string(self._conn) as client:
            receiver = client.get_queue_receiver(self._queue)
            with receiver:
                for msg in receiver:
                    envelope = RequestEnvelope.model_validate_json(str(msg))
                    handler(envelope)
                    receiver.complete_message(msg)


def build_queue() -> QueueBackend:
    settings = get_settings()
    if settings.service_bus_connection_string and not settings.fake_providers:
        return ServiceBusQueue(
            settings.service_bus_connection_string, settings.service_bus_queue_name
        )
    return FileQueue()
