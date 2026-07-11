"""Centralised configuration loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "local"
    log_level: str = "INFO"

    # When true, calendar/email use in-memory fakes and the agent uses a local
    # deterministic model adapter. No external (Google/Azure) calls are made.
    fake_providers: bool = True

    # Database
    database_url: str = "postgresql+psycopg://appt:appt@localhost:5432/appointments"

    # Scheduling defaults
    default_opening_start: str = "09:00"
    default_opening_end: str = "17:00"
    slot_minutes: int = 30
    default_timezone: str = "UTC"

    # Queue
    service_bus_connection_string: str = ""
    service_bus_queue_name: str = "appointment-requests"

    # Remote MCP servers
    mcp_resource_details_url: str = "http://localhost:8081/mcp"
    mcp_calendar_url: str = "http://localhost:8082/mcp"
    mcp_email_url: str = "http://localhost:8083/mcp"
    mcp_api_key: str = "local-dev-key"

    # Magic-link auth
    magic_link_secret: str = "change-me-in-prod"
    magic_link_ttl_minutes: int = 15
    public_base_url: str = "http://localhost:8080"

    # Google
    google_credentials_file: str = "credentials.json"
    google_token_file: str = "token.json"
    gmail_sender: str = "appointments@example.com"

    # Azure AI Foundry
    azure_ai_project_endpoint: str = ""
    azure_ai_agent_model: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()