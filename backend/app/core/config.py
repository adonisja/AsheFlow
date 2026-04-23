from typing import List
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    aws_region: str
    aws_cognito_user_pool_id: str
    aws_cognito_app_client_id: str

    # Required — no default so a missing .env causes a clear startup error rather
    # than silently connecting to a hardcoded dev credential in production.
    database_url: str

    # Redis — used for dispatch confirmation state
    redis_url: str = "redis://localhost:6379/0"

    # Shared secret for internal bot → backend webhook calls
    internal_secret: str = "change-me-in-production"

    # Comma-separated list of allowed CORS origins.
    # Dev default covers common Vite/CRA ports; override in production.
    cors_origins: str = (
        "http://localhost:3000,http://localhost:3001,http://localhost:3002,"
        "http://localhost:3003,http://localhost:3004,http://localhost:3005,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    def get_cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"

settings = Settings()
