from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    discord_bot_token: str

    # ------------------------------------------------------------------ #
    # API / auth                                                           #
    # ------------------------------------------------------------------ #
    api_base_url: str = "http://backend:8000/api/v1"

    # ADR-363 — the bot is migrating to an OAuth2 client_credentials machine
    # identity. These stay OPTIONAL during the cutover so a rollback needs an
    # env change rather than a deploy, and are removed once M2M is proven.

    # Machine identity. When both are set the bot uses client_credentials and
    # never touches the username/password path.
    cognito_m2m_client_id: str | None = None
    cognito_m2m_client_secret: str | None = None
    cognito_oauth_domain: str | None = None

    aws_cognito_user_pool_id: str
    aws_cognito_client_id: str
    aws_region: str = "us-east-1"

    internal_secret: str = "change-me-in-production"

    class Config:
        env_file = ".env"
        extra = "ignore"  # guild/channel/role IDs have moved to DB; ignore stale .env keys


settings = Settings()
