"""
Set minimum required environment variables before any router module is imported.

Router modules import app.core.config.settings at module load time (not inside
a function). pytest_configure runs before collection, so env vars set here are
visible when Python first imports the router module.

Problem: pydantic-settings reads the root .env file directly (not via
os.environ), and that file contains stale Docker-compose fields that are no
longer in the Settings model. We inject a pre-built Settings stub into
sys.modules under app.core.config before any router module is imported.
"""
import sys
import types
from unittest.mock import MagicMock


def pytest_configure(config):
    stub_settings = MagicMock()
    stub_settings.app_env = "test"
    stub_settings.database_url = "sqlite:///:memory:"
    stub_settings.aws_region = "us-east-1"
    stub_settings.aws_cognito_user_pool_id = "us-east-1_test"
    stub_settings.aws_cognito_app_client_id = "test-client-id"
    stub_settings.redis_url = "redis://localhost:6379/0"
    stub_settings.internal_secret = "test-secret"

    config_module = types.ModuleType("app.core.config")
    config_module.settings = stub_settings
    config_module.Settings = MagicMock(return_value=stub_settings)

    sys.modules.setdefault("app.core.config", config_module)
