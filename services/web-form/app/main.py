"""FastAPI application for the web-form edge service.

- GraphQL API + GraphiQL playground (Strawberry) at /graphql
- /verify magic-link landing endpoint
- / serves a minimal booking form
- /healthz health probe
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from strawberry.fastapi import GraphQLRouter

from app import auth
from app.schema import schema

app = FastAPI(title="Appointment Web/Form Service")

# graphiql=True enables the built-in GraphQL Playground at /graphql
graphql_app = GraphQLRouter(schema, graphiql=True)
app.include_router(graphql_app, prefix="/graphql")

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


@app.get("/verify", response_class=HTMLResponse)
def verify(token: str) -> str:
    ok = auth.verify_magic_link(token)
    msg = "Email verified â€” you can return to the form and book." if ok else "Invalid or expired link."
    return f"<html><body><h2>{msg}</h2></body></html>"


if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
