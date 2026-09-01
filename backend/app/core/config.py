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
            is_local = "localhost" in db_lower or "127.0.0.1" in db_lower or "@postgres:" in db_lower
            if not has_ssl and not is_local:
                raise RuntimeError(
                    "DATABASE_URL must include sslmode=require (or verify-full) in staging/production. "
                    "Unencrypted database connections are not permitted. "
                    "Example: postgresql://user:pass@host:5432/db?sslmode=require"
                )

        # ADR-283. The ORE certificate settings default to "" so a deploy WITHOUT
        # the S3 infrastructure degrades (uploads 503) rather than crashing. That
        # is still the intent for a fresh environment.
        #
        # What it does not cover is the case that actually happened: the bucket
        # and key exist, and the config was LOST. CI rebuilds backend/.env from
        # SSM Parameter Store on every deploy, so any key absent from the store
        # is erased. An empty value then reads as "feature intentionally off",
        # and a trainee's certificate upload starts failing with nobody alerted.
        #
        # The two states are indistinguishable from inside the process, so the
        # environment decides: staging and production have the infrastructure
        # provisioned, therefore an empty value there is a wiped config, not a
        # choice. Fail at startup, where it is one log line, instead of at a
        # trainee's upload, where it is a support ticket.
        if self.app_env not in {"development", "test"}:
            missing_ore = [
                name
                for name, value in (
                    ("ORE_CERTIFICATE_BUCKET", self.ore_certificate_bucket),
                    ("ORE_CERTIFICATE_KMS_KEY_ID", self.ore_certificate_kms_key_id),
                )
                if not value
            ]
            if missing_ore:
                raise RuntimeError(
                    f"{', '.join(missing_ore)} is empty in a non-development environment. "
                    "The S3 infrastructure is provisioned in staging and production, so an "
                    "empty value means the config was lost rather than deliberately disabled "
                    "(CI rebuilds backend/.env from SSM Parameter Store, dropping any key "
                    "absent from it). Restore the parameter under /asheflow/<env>/ and "
                    "redeploy. See ADR-283."
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

    # ADR-219: null the customer delivery address on delivery rows this many hours
    # after the route date (block_key + counts kept). Disputes are same-shift; the
    # troublesome signal is distilled to BuildingProfile (ADR-218). 0 disables.
    delivery_address_retention_hours: int = 48

    # ── ADR-281: ORE completion certificates ────────────────────────────────
    # A phase-0 certificate carries the trainee's name and an Amazon training
    # id, so the FILE is short-lived. The attestation on the training record is
    # what persists; this is only the evidence window.
    #
    # Empty bucket name disables the feature: uploads 503 with a clear message
    # rather than throwing a boto3 error at a trainee. That is deliberate — a
    # deploy without the infrastructure should degrade, not crash.
    ore_certificate_bucket: str = ""
    ore_certificate_kms_key_id: str = ""
    ore_certificate_retention_hours: int = 48
    # 5 minutes: long enough to open a PDF, short enough that a URL copied out
    # of a browser's history or a screenshot is useless by the time it lands
    # anywhere else.
    ore_presign_ttl_seconds: int = 300
    ore_max_upload_bytes: int = 10 * 1024 * 1024

    # ADR-221: redact a departed employee's denormalized name copies this many days
    # after deactivation (covers post-departure disputes/references). 0 disables.
    employee_name_retention_days: int = 180

    # ADR-216 Phase 3: per-stop cutoff-urgency gradient windows (minutes before a
    # building's closing/break cutoff). A stop is RED (urgent) within
    # stop_urgent_window_minutes of its cutoff, YELLOW (caution) the
    # stop_caution_window_minutes immediately before that, else green/blue.
    # Surfaced on the route-detail response so client colours match this tuning.
    stop_urgent_window_minutes: int = 60
    stop_caution_window_minutes: int = 60

    # ADR-227: prune notifications older than this many days (applies to read AND
    # unread — an operational notice's shift is long over after a few days).
    # Expired notifications (past expires_at) are pruned regardless of age. The
    # inbox already hides expired/old ones; this reclaims the storage. 0 disables.
    notification_retention_days: int = 3

    # NYC GeoClient API v2 — used for address enrichment at manifest ingestion time.
    # Register at https://api.nyc.gov/ (free, requires NYC account).
    # v2 auth: subscription-key query param only — no app_id needed.
    # Leave unset in development/test; enrichment falls back to raw address parsing.
    geoclient_app_key: str = ""

    # If the fraction of packages that fail GeoClient enrichment exceeds this
    # threshold, the task marks the manifest as "failed" (not "ready") so that
    # sort is blocked rather than silently running on unusable data.
    geoclient_failure_threshold: float = 0.80

    # NYC Open Data (Socrata) — AddressPoint enumeration for the zone bootstrap
    # (ADR-303 D7/D8). The App Token is a RATE-LIMIT identifier for public data,
    # not an authorisation grant: anonymous requests work but are throttled by IP.
    # Token-optional on purpose — requiring it would make the feature untestable
    # until one is registered. Get one at https://data.cityofnewyork.us (Sign in
    # -> Developer Settings -> Create New App Token).
    socrata_app_token: str = ""
    # AddressPoint dataset id. Pinned rather than hardcoded so a dataset
    # migration is a config change, not a code change.
    socrata_addresspoint_dataset: str = "uf93-f8nk"

    # Fernet key for encrypting trainee credentials (flex email, clock-in code).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Required — no default. Add CREDENTIAL_ENCRYPTION_KEY to .env locally; set via env var in staging/prod.
    credential_encryption_key: str

    # Feature flag — ADP payroll integration.
    # Keep False until the integration is fully tested and signed off.
    # Flip to True via ADP_ENABLED=true in the environment to enable all /adp endpoints.
    adp_enabled: bool = False

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

    cors_allow_methods: str = "GET,POST,PUT,PATCH,DELETE"
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
