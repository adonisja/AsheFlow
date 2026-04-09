from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    aws_region: str
    aws_cognito_user_pool_id: str
    aws_cognito_app_client_id: str
    
    database_url: str = "postgresql://asheflow:asheflow_dev_password@localhost:5432/asheflow_db"

    class Config:
        env_file = ".env"

settings = Settings()
