from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    discord_bot_token: str
    discord_guild_id: int

    # ------------------------------------------------------------------ #
    # Named channels                                                       #
    # ------------------------------------------------------------------ #
    discord_drivers_channel_id: int
    discord_trainers_channel_id: int
    discord_general_channel_id: int

    # ------------------------------------------------------------------ #
    # Discord server role IDs                                              #
    # Roles that always have read access to ALL truck channels.            #
    # ------------------------------------------------------------------ #
    discord_role_admin: int
    discord_role_manager: int
    discord_role_asheflow: int
    discord_role_bot: int
    discord_role_dispatch: int
    discord_role_driver: int
    discord_role_captain: int
    discord_role_walker: int

    # ------------------------------------------------------------------ #
    # API / auth                                                           #
    # ------------------------------------------------------------------ #
    api_base_url: str = "http://backend:8000/api/v1"

    bot_username: str
    bot_password: str

    aws_cognito_user_pool_id: str
    aws_cognito_client_id: str
    aws_region: str = "us-east-1"

    confirmation_window_hours: int = 2
    internal_secret: str = "change-me-in-production"

    # Optional — channel used as the landing target for new-employee invite links.
    # Defaults to discord_drivers_channel_id if not set.
    discord_invite_channel_id: int = 0

    class Config:
        env_file = ".env"


settings = Settings()
