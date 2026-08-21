"""ADR-283 — an empty ORE certificate config must not be silently accepted.

THE FAILURE THIS PREVENTS
-------------------------
CI rebuilds `backend/.env` on every deploy by copying a root `.env` that is
itself regenerated from SSM Parameter Store. Any key absent from the store is
therefore ERASED on deploy, not preserved. `ORE_CERTIFICATE_BUCKET` was added
to the server by hand and never to the store, so the next deploy would have
removed it.

The removal is quiet by design: the setting defaults to `""`, and an empty
bucket disables uploads with a 503 rather than crashing. That graceful
degradation is correct for an environment with no S3 infrastructure — and
exactly wrong for staging and production, where the bucket exists and an empty
value can only mean the config was lost. A trainee's certificate upload starts
failing and no container looks unhealthy.

The two states are indistinguishable from inside the process, so the
environment decides.
"""
import pytest

from app.core.config import Settings

_BASE = dict(
    aws_region="us-east-2",
    aws_cognito_user_pool_id="us-east-2_test",
    aws_cognito_app_client_id="testclientid",
    database_url="postgresql://u:p@postgres:5432/db",
    credential_encryption_key="k" * 32,
    internal_secret="s" * 64,
    cors_origins="https://staging.asheflow.com",
)

_ORE = dict(
    ore_certificate_bucket="asheflow-ore-certificates-staging",
    ore_certificate_kms_key_id="8c76dc07-3e35-4f7e-a870-fbea333bb8e7",
)


def _settings(**over):
    kwargs = {**_BASE, **_ORE, **over}
    return Settings(_env_file=None, **kwargs)


class TestNonDevelopmentRefusesEmptyOreConfig:
    @pytest.mark.parametrize("env", ["production", "staging"])
    @pytest.mark.parametrize(
        "blank", ["ore_certificate_bucket", "ore_certificate_kms_key_id"]
    )
    def test_it_refuses_to_start(self, env, blank):
        """Fail at startup — one log line — instead of at a trainee's upload,
        which is a support ticket days later."""
        with pytest.raises(RuntimeError) as exc:
            _settings(app_env=env, **{blank: ""})
        assert blank.upper() in str(exc.value)

    def test_the_error_names_the_cause_and_the_fix(self):
        """A bare 'missing setting' sends the operator to .env, which is
        rebuilt on deploy — the durable fix is in Parameter Store."""
        with pytest.raises(RuntimeError) as exc:
            _settings(app_env="production", ore_certificate_bucket="")
        msg = str(exc.value)
        assert "SSM Parameter Store" in msg
        assert "/asheflow/" in msg
        assert "ADR-283" in msg

    def test_both_missing_are_reported_together(self):
        """Reporting one at a time costs a deploy cycle per key."""
        with pytest.raises(RuntimeError) as exc:
            _settings(
                app_env="production",
                ore_certificate_bucket="",
                ore_certificate_kms_key_id="",
            )
        msg = str(exc.value)
        assert "ORE_CERTIFICATE_BUCKET" in msg
        assert "ORE_CERTIFICATE_KMS_KEY_ID" in msg

    def test_a_populated_config_starts_normally(self):
        s = _settings(app_env="production")
        assert s.ore_certificate_bucket == "asheflow-ore-certificates-staging"


class TestDevelopmentStillDegradesGracefully:
    """The original design intent, preserved. A contributor with no AWS
    infrastructure must still be able to boot the app."""

    @pytest.mark.parametrize("env", ["development", "test"])
    def test_empty_is_accepted(self, env):
        s = _settings(app_env=env, ore_certificate_bucket="", ore_certificate_kms_key_id="")
        assert s.ore_certificate_bucket == ""

    def test_uploads_are_disabled_rather_than_erroring(self, monkeypatch):
        """`is_enabled()` is what turns the empty value into a 503 instead of a
        boto3 exception at a trainee. It reads the module-level settings
        singleton, so the test patches that rather than passing an argument."""
        from app.services import ore_certificates

        monkeypatch.setattr(
            ore_certificates.settings, "ore_certificate_bucket", "", raising=True
        )
        assert ore_certificates.is_enabled() is False

        monkeypatch.setattr(
            ore_certificates.settings, "ore_certificate_bucket", "a-bucket", raising=True
        )
        assert ore_certificates.is_enabled() is True
