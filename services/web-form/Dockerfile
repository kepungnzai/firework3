FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY services/shared /app/services/shared
COPY services/web-form /app/services/web-form

RUN pip install --no-cache-dir /app/services/shared /app/services/web-form

WORKDIR /app/services/web-form
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
