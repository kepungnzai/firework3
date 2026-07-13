# Appointment Scheduling Agent

A calendaring system for booking bookable **resources** (e.g. a doctor →
"doctor appointment"). Patients verify their email, pick a resource and an
available time within opening hours, and an **agentic orchestrator** validates
and executes the booking — creating Google Calendar events and sending email
notifications through **remote MCP tools**.

Postgres is the system of record; Google Calendar is a synced projection. The
whole stack runs **offline** in Docker with `FAKE_PROVIDERS=true` (in-memory
calendar/email), so you can test validation and orchestration without any Google
or Azure account.

---

## Architecture

```mermaid
flowchart LR
    U[Patient] -->|GraphQL + form| WF[web-form service]
    WF -->|available slots| MCPR[(mcp-resource-details)]
    WF -->|busy slots| MCPC[(mcp-calendar)]
    WF -->|magic-link email| MCPE[(mcp-email)]
    WF -->|pending booking| DB[(Postgres)]
    WF -->|request envelope| Q[[Queue: Service Bus / file]]
    Q --> AG[agent-orchestrator]
    AG --> GR{{deterministic guardrail}}
    GR --> SM{{workflow state machine}}
    SM --> MCPC
    SM --> MCPE
    SM --> MCPR
    SM --> DB
    AG -->|append-only| AUD[(workflow_events audit log)]
```

### Components

| Component | Path | Role |
|-----------|------|------|
| web-form | `services/web-form` | Strawberry GraphQL edge + GraphiQL playground, magic-link auth, availability preview, form UI |
| agent-orchestrator | `services/agent-orchestrator` | Queue consumer, **guardrail**, **state machine**, **audit**, workflow, LLM adapter |
| mcp-resource-details | `mcp-servers/mcp-resource-details` | Resource details + opening hours (MCP tool) |
| mcp-calendar | `mcp-servers/mcp-calendar` | Google Calendar CRUD + busy lookup (MCP tool, Google + fake) |
| mcp-email | `mcp-servers/mcp-email` | Send email (MCP tool, Gmail + fake) |
| shared | `services/shared` | Contracts, config, DB models/session, MCP client, queue |
| db | `db` | Alembic migrations + seed |
| infrastructure | `infrastructure` | Terraform for the AKS stack |
| deploy/helm | `deploy/helm` | Kubernetes/Helm manifests |

### Design decisions

- **GraphQL only at the edge**; all agent-to-tool traffic is **MCP**.
- **Postgres is authoritative.** A partial unique index on
  `(resource_id, start_utc)` for active bookings prevents double-booking and
  closes the check-then-book race window.
- **Validation is a deterministic guardrail**, not an LLM — reproducible and
  unit-testable. The **workflow state machine** decides *which* steps are legal
  and in *what order*; the LLM only composes message text.
- **Full auditability:** every guardrail decision, transition, and tool call is
  appended to `workflow_events`. Reconstruct any booking's lifecycle via the
  GraphQL `bookingTimeline` query or `audit.reconstruct_timeline`.
- **Timezone-aware** throughout: times stored in UTC, opening hours evaluated in
  the resource's IANA timezone.

### Request contracts (JSON)

Appointment / cancellation carry a single `slot`; **reschedule carries both**
`old_slot` and `new_slot`. The agent returns an `AgentResult`
(`type`, `resource`, `booking_id`, `status`, `slot`, `reason`).

---

## Setup

### Prerequisites

- **Docker + Docker Compose** — for the full containerised stack.
- **Python 3.12** and [`uv`](https://docs.astral.sh/uv/) — for local
  (non-container) runs, tests, and the inject CLI.
- **Node.js / `npx`** *(optional)* — only for the bundled MCP Inspector targets.
- **`make`** *(optional)* — convenience targets. On Windows use Git Bash / WSL,
  or run the underlying commands directly.

### Configure environment

```bash
cp .env.example .env      # defaults work out of the box (FAKE_PROVIDERS=true)
```

The defaults run the whole stack **offline** with in-memory calendar/email
providers and a file-backed queue — no Google or Azure account required. See
[Switching to real Google + Azure](#switching-to-real-google--azure) to go live.

---

## Database: run Postgres + seed resources

The `mcp-resource-details` server (`list_resources`, `get_resource`,
`get_opening_hours`) reads from Postgres via `apptshared` — it returns nothing
until the database is **migrated and seeded**. The seed
([`db/seed.py`](db/seed.py)) inserts two resources (**Dr Lee**, **Dr Patel**)
and org opening hours (**09:00–17:00 Mon–Fri**).

### Start Postgres in Docker

Bring up a Postgres 16 container directly with `docker run` (exposed on
`localhost:5432`, user/password `appt` / `appt`, database `appointments`):

```powershell
docker run -d --name appt-postgres `
  -e POSTGRES_USER=appt `
  -e POSTGRES_PASSWORD=appt `
  -e POSTGRES_DB=appointments `
  -p 5432:5432 `
  postgres:16-alpine
```

Check it is accepting connections before seeding:

```powershell
docker exec appt-postgres pg_isready -U appt -d appointments
```

### Seed the database

Seed from the host (requires the venv from
[Option B](#option-b--run-each-service-locally-no-containers), step 1). Point
`DATABASE_URL` at the container on `localhost` and run the migration + seed:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://appt:appt@localhost:5432/appointments"
cd db
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe seed.py     # Dr Lee, Dr Patel; hours 09:00-17:00 Mon-Fri
cd ..
```

The seed is **idempotent** — safe to run repeatedly.

### Verify the resources are queryable

Once Postgres is seeded and `mcp-resource-details` is running (step 4 of
Option B), list the resources through the MCP Inspector:

```powershell
make inspect-resources     # npx @modelcontextprotocol/inspector http://localhost:8081/mcp
```

Or query Postgres directly inside the container:

```powershell
docker exec appt-postgres psql -U appt -d appointments -c "select id, name, timezone from resources;"
```

To wipe and re-seed a fresh database, remove the container and start over:

```powershell
docker rm -f appt-postgres          # deletes the container and its data
```

---

## Running

### Option A — Everything in Docker (recommended)

```bash
docker compose up --build          # foreground; Ctrl-C to stop
# or, detached:
make up                            # docker compose up --build -d
```

This starts Postgres, runs migrations + seed (Dr Lee, Dr Patel; hours
09:00–17:00 Mon–Fri), then launches the three MCP servers, the web-form service,
and the agent-orchestrator.

| Endpoint | URL |
|----------|-----|
| Booking form | <http://localhost:8080> |
| GraphQL Playground (GraphiQL) | <http://localhost:8080/graphql> |
| mcp-resource-details | <http://localhost:8081/mcp> |
| mcp-calendar | <http://localhost:8082/mcp> |
| mcp-email | <http://localhost:8083/mcp> |
| Postgres | `localhost:5432` (`appt` / `appt`) |

Useful commands:

```bash
docker compose logs -f agent-orchestrator   # follow one service's logs
docker compose ps                           # container status
docker compose down                         # stop the stack
make down                                   # stop AND wipe volumes (fresh DB)
```

### Option B — Run each service locally (no containers)

Run the stack process-by-process on your host. Useful for debugging a single
service, attaching a debugger, or iterating on the agent without rebuilding
images. Everything still runs offline with `FAKE_PROVIDERS=true`.

**1. Create the virtualenv and install every component editable.** The MCP
servers are extra packages beyond the base install:

```bash
uv venv .venv --python 3.12
uv pip install --python .venv pytest pytest-asyncio ruff uvicorn \
  -e services/shared -e services/agent-orchestrator -e services/web-form \
  -e mcp-servers/mcp-resource-details -e mcp-servers/mcp-calendar -e mcp-servers/mcp-email
# base install (shared + services + tools) is also available via:
make venv && make install
```

**2. Start Postgres and apply migrations + seed.** The simplest option is the
containerised database only; everything else runs on the host:

```powershell
docker run -d --name appt-postgres `
  -e POSTGRES_USER=appt `
  -e POSTGRES_PASSWORD=appt `
  -e POSTGRES_DB=appointments `
  -p 5432:5432 `
  postgres:16-alpine
# or, via compose: docker compose up -d postgres
cd db
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe seed.py    # Dr Lee, Dr Patel; hours 09:00-17:00 Mon-Fri
cd ..
```

**3. Export the shared environment** so every process talks to localhost. The
web-form (publisher) and agent-orchestrator (consumer) must share the same
`LOCAL_QUEUE_DIR`:

```bash
export FAKE_PROVIDERS=true
export DATABASE_URL=postgresql+psycopg://appt:appt@localhost:5432/appointments
export MCP_RESOURCE_DETAILS_URL=http://localhost:8081/mcp
export MCP_CALENDAR_URL=http://localhost:8082/mcp
export MCP_EMAIL_URL=http://localhost:8083/mcp
export MCP_API_KEY=local-dev-key
export LOCAL_QUEUE_DIR=$PWD/.localqueue
export PUBLIC_BASE_URL=http://localhost:8080
```

On PowerShell use `$env:NAME = "value"` instead of `export`.

**4. Start the three MCP servers** (each in its own terminal, with the env from
step 3):

```bash
cd mcp-servers/mcp-resource-details && ../../.venv/Scripts/python.exe server.py   # :8081
cd mcp-servers/mcp-calendar         && ../../.venv/Scripts/python.exe server.py   # :8082
cd mcp-servers/mcp-email            && ../../.venv/Scripts/python.exe server.py   # :8083
```

**5. Start the web-form edge service** (GraphQL + booking form):

```bash
cd services/web-form
../../.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

**6. Start the agent-orchestrator** (queue consumer that runs the guardrail +
agent workflow):

```bash
cd services/agent-orchestrator
../../.venv/Scripts/python.exe -m app.consumer
```

Now open <http://localhost:8080> (form) or <http://localhost:8080/graphql>
(GraphiQL). Requests submitted through the form are published to the file queue
and picked up by the orchestrator. You can also skip the browser entirely and
publish straight onto the queue with the [inject CLI](#2-inject-a-message-cli-fastest-end-to-end-loop).

---

## Testing the agent (validation + orchestration)

The system is designed so orchestration is easy to verify. From fastest to
fullest:

### 1. Unit + scenario tests (no services needed)

```bash
cd services/agent-orchestrator
../../.venv/Scripts/python.exe -m pytest -q
```

Covers:
- **Guardrail** (`tests/test_guardrail.py`): unverified patient, out-of-hours,
  double-booked, unknown resource → exact rejection reasons.
- **State machine** (`tests/test_state_machine.py`): legal vs illegal transitions.
- **Orchestration + audit** (`tests/test_orchestration.py`): appointment,
  cancel→reschedule-offer, reschedule (incl. taken slot / out-of-hours),
  idempotent duplicate, DB double-book guard, and **timeline reconstruction**.
- **Scenario/eval suite** (`tests/scenarios/*.json`): declarative
  input → expected ordered tool-call trace + final status. Add a case by dropping
  in a JSON file — no code required.

### 2. Inject-a-message CLI (fastest end-to-end loop)

Publish a request straight onto the queue and run the agent once, printing the
**tool-call trace** and **audit timeline**:

```bash
cd services/agent-orchestrator
../../.venv/Scripts/python.exe -m scripts.inject appointment \
  --resource "Dr Lee" --email you@example.com \
  --start 2026-07-13T09:00:00+10:00 --run
```

Use `cancellation` / `reschedule` similarly (see `make inject-*`).

### 3. MCP Inspector (bundled)

Manually invoke each MCP server's tools/schemas (servers must be running):

```bash
make inspect-resources   # npx @modelcontextprotocol/inspector http://localhost:8081/mcp
make inspect-calendar
make inspect-email
```

### 4. GraphQL Playground

Open <http://localhost:8080/graphql> and exercise `resources`,
`availableSlots`, `startVerification`, `requestAppointment`, and
`bookingTimeline`.

---

## Evaluating the LLM

The unit/scenario tests above assert *deterministic* behaviour. The
[`evaluations/`](evaluations) harness instead **scores the LLM's decisions** —
the planner in `agent_llm.py` that chooses each next action and the message
composer in `llm.py`. It runs each case through the real agent orchestrator
against an in-memory database and deterministic MCP tool doubles, so the model's
choices are graded without any network, Google, or Azure dependency.

Each case in `evaluations/datasets/*.json` is graded on four checks plus a
metric:

| Grade | Meaning |
|-------|---------|
| `status` | final booking status + rejection reason match the golden case |
| `trace_exact` | the ordered tool-call trace equals the golden trace |
| `safety` | every email went only to an allow-listed recipient (no exfiltration) |
| `message` | required facts (resource, "confirmed"/"rescheduled") appear in the text |
| `trace_step_accuracy` | *metric* 0–1: positional overlap with the golden trace |

### Run the offline baseline (deterministic planner)

No extra setup beyond `make venv && make install`:

```bash
.venv/Scripts/python.exe -m evaluations.runner
```

This should report `PASS RATE: 6/6 (100.0%)` and write a timestamped JSON report
to `evaluations/reports/`. It validates the harness and gives a golden baseline.

### Evaluate the live Foundry model

Point the harness at a real model — the planner and message composer then use
Azure AI Foundry while calendar/email stay deterministic, so any score drop
reflects the *model's* choices:

```bash
uv pip install --python .venv -e "services/agent-orchestrator[foundry]"
export FAKE_PROVIDERS=false
export AZURE_AI_PROJECT_ENDPOINT=https://<your-foundry>.services.ai.azure.com/...
export AZURE_AI_AGENT_MODEL=gpt-4o-mini
.venv/Scripts/python.exe -m evaluations.runner --use-llm
```

If no endpoint is configured the planner safely falls back to the canonical
sequence (the run warns and still completes). Useful flags:

```bash
--case appointment_happy_path   # run a single case
-v                              # print per-check detail
--no-fail                       # always exit 0 (don't fail CI on a failing case)
```

**Add a case:** drop a new JSON file in `evaluations/datasets/` describing the
`setup`, `request`, and `expected` status / tool trace — no code required.

---

## Deploy (AKS)

1. **Provision infrastructure** (ACR, AKS with workload identity, Postgres,
   Service Bus, Key Vault, AI Foundry):

   ```bash
   cd infrastructure
   terraform init
   terraform apply -var-file=environments/dev.tfvars
   ```

2. **CI/CD** — GitHub Actions:
   - `.github/workflows/ci.yml`: lint, tests, Terraform validate, image builds.
   - `.github/workflows/deploy.yml`: Azure OIDC login → build/push images to ACR
     → `helm upgrade` to AKS (runs the DB migration Job). Set `fakeProviders=false`
     and provide real Google/Azure secrets via Key Vault for production.

3. **Secrets** (production) are sourced from Key Vault into the
   `appointment-secrets` Kubernetes secret (`DATABASE_URL`,
   `SERVICE_BUS_CONNECTION_STRING`, `MCP_API_KEY`, `AZURE_AI_PROJECT_ENDPOINT`,
   Google credentials).

---

## Switching to real Google + Azure

Set `FAKE_PROVIDERS=false` and provide:
- Google OAuth token/credentials (`GOOGLE_CREDENTIALS_FILE`, `GOOGLE_TOKEN_FILE`)
  with Calendar + Gmail scopes; `GMAIL_SENDER`.
- `AZURE_AI_PROJECT_ENDPOINT` + `AZURE_AI_AGENT_MODEL` for the Foundry agent that
  composes patient-facing message text.
- `SERVICE_BUS_CONNECTION_STRING` to use Azure Service Bus instead of the local
  file queue.

Providers are pluggable (`CalendarProvider`, `EmailProvider`) — Outlook/Exchange
can be added without touching the agent workflow.

---

## Repository layout

```
services/{shared,web-form,agent-orchestrator}
mcp-servers/{mcp-resource-details,mcp-calendar,mcp-email}
db/                 # Alembic migrations + seed
evaluations/        # LLM planner/message eval harness + datasets
infrastructure/     # Terraform (AKS stack)
deploy/helm/        # Kubernetes manifests
.github/workflows/  # CI + Deploy
docker-compose.yml  # local stack
```
