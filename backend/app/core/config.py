from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from urllib.parse import urlparse


_ALLOWED_BOT_HOSTS = {"bot", "localhost", "127.0.0.1"}


class Settings(BaseSettings):
    aws_region: str
    aws_cognito_user_pool_id: str
    aws_cognito_app_client_id: str

    app_env: str = "development"

    # Required — no default so a missing .env causes a clear startup error rather
    # than silently connecting to a hardcoded dev credential in production.
    database_url: str

    # Redis — used for dispatch confirmation state
    redis_url: str = "redis://localhost:6379/0"

    # Shared secret for internal bot → backend webhook calls.
    # Must be overridden via environment variable before deployment.
    internal_secret: str = "change-me-in-production"
    bot_internal_url: str = "http://bot:8001"


    def __init__(self, **data):
        super().__init__(**data)
        if self.app_env != "development" and self.internal_secret == "change-me-in-production":
            raise RuntimeError(
                "INTERNAL_SECRET must be set to a strong random value in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        
        if "localhost" in self.cors_origins and self.app_env not in {"development", "test"}:
            raise RuntimeError(
                "CORS_ORIGINS contains 'localhost' in a non-development environment. "
                "Set CORS_ORIGINS to your actual production/staging domain(s) before deploying."
            )

        # GDPR Art. 32 / CCPA §1798.150 — encryption in transit is mandatory in production.
        # AWS RDS requires sslmode=require (or prefer/verify-full) in the connection string.
        # If the database_url does not include SSL params and we are not in development,
        # the connection would be unencrypted. Fail fast here rather than silently skip.
        if self.app_env not in {"development", "test"}:
            db_lower = self.database_url.lower()
            has_ssl = "sslmode=require" in db_lower or "sslmode=verify" in db_lower
            is_local = "localhost" in db_lower or "127.0.0.1" in db_lower
            if not has_ssl and not is_local:
                raise RuntimeError(
                    "DATABASE_URL must include sslmode=require (or verify-full) in staging/production. "
                    "Unencrypted database connections are not permitted. "
                    "Example: postgresql://user:pass@host:5432/db?sslmode=require"
                )
    
    

    @field_validator("bot_internal_url")
    @classmethod
    def validate_bot_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"BOT_INTERNAL_URL scheme must be http or https, got: {parsed.scheme!r}") 
        if parsed.hostname not in _ALLOWED_BOT_HOSTS:
            raise ValueError(f"BOT_INTERNAL_URL hostname {parsed.hostname!r} is not in the allowed list: {_ALLOWED_BOT_HOSTS}")
        
        return v
        
    # Hours after the driver's departure that walker ratings are accepted.
    # Submissions outside this window are rejected. Default is 6 hours.
    rating_window_hours: int = 6

    # Days after invite before an unverified (pending_verification) employee
    # record is automatically deleted by the Celery cleanup job.
    invite_expiry_days: int = 7

    # Retention period (days) for operational shift records:
    # CrewCompliance, DriverCheckIn, RTSReport, StationHandoff.
    # FLSA §211 requires employment records be kept for at least 3 years (1095 days).
    # Default is 1095 (3 years); set to 0 to disable automatic purge.
    operational_record_retention_days: int = 1095

    # NYC GeoClient API — used for address enrichment at manifest ingestion time.
    # Register at https://api.nyc.gov/  (free, requires NYC account).
    # Leave unset in development/test; enrichment task will skip GeoClient calls.
    geoclient_app_id: str = ""
    geoclient_app_key: str = ""

    # Fernet key for encrypting trainee credentials (flex email, clock-in code).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Required — no default. Add CREDENTIAL_ENCRYPTION_KEY to .env locally; set via env var in staging/prod.
    credential_encryption_key: str

    # SES sender address — must be a verified identity in SES.
    ses_from_email: str = "AsheFlow <noreply@asheflow.com>"

    # Public base URL of the web app — used to build invite links in emails.
    app_base_url: str = "http://localhost:5173"

    # Comma-separated list of allowed CORS origins.
    # Dev default covers common Vite/CRA ports; override in production.
    cors_origins: str = (
        "http://localhost:3000,http://localhost:3001,http://localhost:3002,"
        "http://localhost:3003,http://localhost:3004,http://localhost:3005,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    cors_allow_methods: str = "GET,POST,PATCH,DELETE"
    cors_allow_headers: str = "Authorization,Content-Type"

    def get_cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def get_cors_methods(self) -> List[str]:
        if self.app_env == "development":
            return ["*"]
        return [m.strip() for m in self.cors_allow_methods.split(",") if m.strip()]

    def get_cors_headers(self) -> List[str]:
        if self.app_env == "development":
            return ["*"]
        return [h.strip() for h in self.cors_allow_headers.split(",") if h.strip()]

    model_config = SettingsConfigDict(env_file=(".env", "backend/.env"), extra="ignore")



settings = Settings()
