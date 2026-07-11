FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY services/shared /app/services/shared
COPY db /app/db

RUN pip install --no-cache-dir /app/services/shared alembic

WORKDIR /app/db

CMD ["sh", "-c", "alembic upgrade head && python seed.py"]