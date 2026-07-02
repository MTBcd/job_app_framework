"""Application settings — single source of truth, no import-time side effects.

Replaces the V0 pattern (module-level ``load_dotenv(override=True)`` plus two
competing settings objects). Legacy CLI modules keep their own config until
they are ported; everything new reads from here.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: str = "sqlite:///./jobapp.db"

    # Observability
    sentry_dsn: str = ""

    # Auth (Clerk) — filled in when the web app lands
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""

    # Billing (Stripe)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # AI provider
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5"

    # Symmetric key for encrypting user mailbox credentials at rest (Fernet).
    credentials_encryption_key: str = ""

    # Safety defaults carried over from V0
    default_daily_send_cap: int = 20
    blocked_recipient_domains: str = "gmail.com,yahoo.com,hotmail.com,outlook.com"


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
