from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    discord_bot_token: str

    # ------------------------------------------------------------------ #
    # API / auth                                                           #
    # ------------------------------------------------------------------ #
    api_base_url: str = "http://backend:8000/api/v1"

    bot_username: str
    bot_password: str

    aws_cognito_user_pool_id: str
    aws_cognito_client_id: str
    aws_region: str = "us-east-1"

    internal_secret: str = "change-me-in-production"

    class Config:
        env_file = ".env"
        extra = "ignore"  # guild/channel/role IDs have moved to DB; ignore stale .env keys


settings = Settings()
