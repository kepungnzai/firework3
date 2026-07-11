FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY services/shared /app/services/shared
COPY mcp-servers/mcp-email /app/mcp-servers/mcp-email

RUN pip install --no-cache-dir /app/services/shared /app/mcp-servers/mcp-email

WORKDIR /app/mcp-servers/mcp-email
EXPOSE 8083

CMD ["python", "server.py"]