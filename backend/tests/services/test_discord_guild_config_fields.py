"""Every `discord_role_*` column must reach DiscordGuildConfig.

THE OUTAGE THIS FIXES
---------------------
Migration ff90779895f6 split trainer out of the captain role and added
`company_configs.discord_role_trainer`. It updated three of five places — the
DB column, the ORM column, and internal.py's reader — but NOT this dataclass or
its two constructors.

So `cfg.role_trainer` raised AttributeError on every guild-config fetch:

    GET /api/v1/internal/guild-config/{company_id}  ->  500
    AttributeError: 'DiscordGuildConfig' object has no attribute 'role_trainer'

The bot reads that 500 as "Discord not configured" and skips silently:

    hub_finalize_truck: Discord not configured for company ... — skipping.

Which is why publish returned 200 with no notification. The failure was three
hops from where it showed.
"""
import dataclasses
import inspect

from app.models.company import CompanyConfig
from app.services import company_config as cc
from app.services.company_config import DiscordGuildConfig

_FIELDS = {f.name for f in dataclasses.fields(DiscordGuildConfig)}
_SRC = inspect.getsource(cc)


def test_every_discord_role_column_has_a_dataclass_field():
    """The check that would have caught this at migration time: the model and
    the dataclass must agree on the set of roles."""
    columns = {
        c.name[len("discord_role_"):]
        for c in CompanyConfig.__table__.columns
        if c.name.startswith("discord_role_")
    }
    missing = {f"role_{r}" for r in columns} - _FIELDS
    assert not missing, (
        f"CompanyConfig has these discord_role_* columns with no "
        f"DiscordGuildConfig field: {sorted(missing)}"
    )


def test_role_trainer_specifically():
    """Named because it is the one that broke, and the one a revert would drop."""
    assert "role_trainer" in _FIELDS


def test_both_constructors_set_every_field():
    """Two call sites build this dataclass — the empty branch for a company with
    no config row, and the populated branch. A field added to one and not the
    other raises TypeError on the path nobody tested."""
    for field in _FIELDS:
        if field == "is_configured":      # a property, not a field
            continue
        assert f"{field}=None" in _SRC or f"{field}: int | None" in _SRC, field
        assert f"{field}        = row.discord_{field}" in _SRC or f"{field}=None" in _SRC, field


def test_a_config_with_no_row_constructs():
    """The empty branch. A missing kwarg here is a TypeError for every company
    that has not configured Discord."""
    cfg = DiscordGuildConfig(**{f: None for f in _FIELDS})
    assert cfg.role_trainer is None
    assert cfg.is_configured is False
