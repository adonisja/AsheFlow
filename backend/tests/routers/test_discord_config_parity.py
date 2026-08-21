"""The Discord config schema, response and column set must agree (ADR-256).

Five layers carry each discord_* field: the CompanyConfig column, the request schema,
the response schema, the internal guild-config endpoint the bot reads, and the bot's
own dataclass. A field added to some but not all of them fails SILENTLY — the PATCH
loop is `setattr(config, field, value)` over `model_dump(exclude_unset=True)`, so a
field missing from the request schema is simply never written, and the UI reports
success while nothing was saved.

That is not hypothetical: discord_role_trainer and discord_captains_channel_id were
each added to the model first and had to be walked through four more files by hand.
"""
import pytest

from app.models.company import CompanyConfig
from app.routers.companies import DiscordConfigUpdate, DiscordConfigResponse


def _discord_columns() -> set[str]:
    return {c for c in CompanyConfig.__table__.columns.keys() if c.startswith("discord_")}


def test_request_schema_covers_every_discord_column():
    """A column absent from the request schema can never be set from the UI."""
    missing = _discord_columns() - set(DiscordConfigUpdate.model_fields)
    assert not missing, (
        f"discord_* columns with no way to set them: {sorted(missing)}. "
        "Add them to DiscordConfigUpdate."
    )


def test_request_schema_has_no_phantom_fields():
    """A request field with no column is accepted, setattr'd onto the ORM object, and
    silently dropped at commit — SQLAlchemy does not raise on an unmapped attribute
    (the trainee-review data-loss bug in the learning guide)."""
    phantom = set(DiscordConfigUpdate.model_fields) - _discord_columns()
    assert not phantom, (
        f"DiscordConfigUpdate fields with no matching column: {sorted(phantom)}"
    )


def test_response_schema_returns_every_discord_column():
    """A column absent from the response is invisible to the settings UI, which
    renders it as unset — so it looks unconfigured no matter what is stored."""
    missing = _discord_columns() - set(DiscordConfigResponse.model_fields)
    assert not missing, (
        f"discord_* columns the API never returns: {sorted(missing)}"
    )


@pytest.mark.parametrize("field", [
    "discord_role_trainer",
    "discord_role_captain",
    "discord_captains_channel_id",
])
def test_adr256_discord_fields_are_wired_end_to_end(field):
    """The three ADR-256 additions, named explicitly.

    role_trainer and role_captain are DIFFERENT roles — the guild's old "Captain"
    was renamed Trainer and a new Captain created — so a missing one is not a
    cosmetic gap: promotions would grant the wrong role or none at all.
    """
    assert field in _discord_columns(), f"{field} missing from CompanyConfig"
    assert field in DiscordConfigUpdate.model_fields, f"{field} cannot be set"
    assert field in DiscordConfigResponse.model_fields, f"{field} is never returned"


def test_internal_guild_config_exposes_what_the_bot_reads():
    """The bot resolves roles and channels from this endpoint's response.

    A field present on the model but absent here reaches the bot as None, and every
    consumer treats None as "not configured" — so the feature silently no-ops rather
    than erroring.
    """
    from app.routers.internal import GuildConfigResponse

    exposed = set(GuildConfigResponse.model_fields)
    for needed in ("role_trainer", "role_captain", "captains_channel_id"):
        assert needed in exposed, (
            f"{needed} is not exposed to the bot — it will read as None and no-op"
        )