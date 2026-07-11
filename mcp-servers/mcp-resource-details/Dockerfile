FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY services/shared /app/services/shared
COPY mcp-servers/mcp-resource-details /app/mcp-servers/mcp-resource-details

RUN pip install --no-cache-dir /app/services/shared /app/mcp-servers/mcp-resource-details

WORKDIR /app/mcp-servers/mcp-resource-details
EXPOSE 8081

CMD ["python", "server.py"]