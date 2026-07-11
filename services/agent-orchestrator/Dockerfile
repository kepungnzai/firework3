FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY services/shared /app/services/shared
COPY services/agent-orchestrator /app/services/agent-orchestrator

RUN pip install --no-cache-dir /app/services/shared /app/services/agent-orchestrator

WORKDIR /app/services/agent-orchestrator

CMD ["python", "-m", "app.consumer"]