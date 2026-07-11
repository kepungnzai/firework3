# Developer convenience targets.
# On Windows, run these with `make` from Git Bash / WSL, or copy the commands.

PY := .venv/Scripts/python.exe

.PHONY: help venv install test lint up down seed inject-appointment inject-cancel inject-reschedule inspect-resources inspect-calendar inspect-email

help:
	@echo "Targets: venv install test lint up down inject-* inspect-*"

venv:
	uv venv .venv --python 3.12

install:
	uv pip install --python .venv pytest pytest-asyncio ruff \
		-e services/shared -e services/agent-orchestrator -e services/web-form

test:
	cd services/agent-orchestrator && ../../$(PY) -m pytest -q

lint:
	uv run ruff check services mcp-servers db

up:
	docker compose up --build -d

down:
	docker compose down -v

# --- Inject-a-message CLI (fastest agent test loop) ---
inject-appointment:
	cd services/agent-orchestrator && ../../$(PY) -m scripts.inject appointment \
		--resource "Dr Lee" --email you@example.com --start 2026-07-13T09:00:00+10:00 --run

inject-cancel:
	cd services/agent-orchestrator && ../../$(PY) -m scripts.inject cancellation \
		--booking $(BOOKING) --email you@example.com --run

inject-reschedule:
	cd services/agent-orchestrator && ../../$(PY) -m scripts.inject reschedule \
		--booking $(BOOKING) --email you@example.com \
		--start 2026-07-13T09:00:00+10:00 --new-start 2026-07-13T14:00:00+10:00 --run

# --- MCP Inspector (bundled via npx) ---
inspect-resources:
	npx @modelcontextprotocol/inspector http://localhost:8081/mcp

inspect-calendar:
	npx @modelcontextprotocol/inspector http://localhost:8082/mcp

inspect-email:
	npx @modelcontextprotocol/inspector http://localhost:8083/mcp