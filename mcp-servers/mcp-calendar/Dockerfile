FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY services/shared /app/services/shared
COPY mcp-servers/mcp-calendar /app/mcp-servers/mcp-calendar

RUN pip install --no-cache-dir /app/services/shared /app/mcp-servers/mcp-calendar

WORKDIR /app/mcp-servers/mcp-calendar
EXPOSE 8082

CMD ["python", "server.py"]