"""`.env.example` must document every setting the app reads.

THE FAILURE THIS PREVENTS
-------------------------
`backend/.env` is regenerated from SSM Parameter Store on every deploy
(ADR-283), so its contents are only ever as complete as the store. `.env.example`
is the reference for which keys the store must hold — and for a local developer,
the reference for what to write by hand.

(An earlier version of this docstring blamed `git merge` for removing the file.
That was wrong: `backend/.env` is gitignored and has never been committed, so
git cannot touch it. The wrong cause survived four retellings and reached a
runbook before anyone ran `git log --all -- backend/.env`.)

When that template is stale, recovery is silently incomplete. It was missing
`CREDENTIAL_ENCRYPTION_KEY` — a REQUIRED setting with no default, so a rebuilt
`.env` would produce a container that crash-loops on `Settings()` validation,
with nothing pointing at the missing key.

WHY A TEST RATHER THAN A RUNBOOK LINE
-------------------------------------
The template drifts by omission: someone adds a setting to `config.py` and
there is nothing to remind them. A test fails at the moment the setting is
added, which is the only moment the author knows what value it should take.
"""
import re
from pathlib import Path

from app.core.config import Settings

_BACKEND = Path(__file__).resolve().parents[1]
_EXAMPLE = _BACKEND / ".env.example"

# Settings supplied by docker-compose rather than .env, or intentionally
# derived. Listed with a reason so the exemption is a decision, not a hole.
_NOT_IN_TEMPLATE = {
    # Injected by docker-compose.yml from POSTGRES_* — the template says so in
    # a comment rather than offering a key that would be ignored in Docker.
    "database_url",
}


def _template_keys() -> set[str]:
    text = _EXAMPLE.read_text()
    # Uncommented assignments only: `KEY=value`. Commented examples are
    # documentation, not declarations.
    return {
        m.group(1).lower()
        for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", text, re.M)
    }


def _settings_fields() -> dict[str, bool]:
    """field name -> is it required (no default)?"""
    out = {}
    for name, field in Settings.model_fields.items():
        out[name] = field.is_required()
    return out


def test_every_required_setting_is_in_the_template():
    """A required setting missing here means a rebuilt .env starts a container
    that crash-loops on validation, with nothing naming the cause."""
    template = _template_keys()
    missing = [
        name
        for name, required in _settings_fields().items()
        if required and name not in template and name not in _NOT_IN_TEMPLATE
    ]
    assert not missing, (
        "these settings are REQUIRED but absent from backend/.env.example, so "
        "an operator rebuilding .env from it gets a container that will not "
        f"start: {sorted(missing)}"
    )


def test_the_template_does_not_document_settings_that_no_longer_exist():
    """A stale key is worse than a missing one — it reads as current and sends
    the operator looking for a setting the app ignores."""
    fields = set(_settings_fields())
    # Compose-level variables live in the template legitimately: they configure
    # docker-compose.yml, not Settings().
    compose_level = {
        "postgres_user", "postgres_password", "postgres_db",
        "cloudwatch_log_group", "aws_default_region",
    }
    stale = [
        k for k in _template_keys()
        if k not in fields and k not in compose_level
    ]
    assert not stale, (
        f"backend/.env.example documents settings the app does not read: {sorted(stale)}"
    )


def test_ore_certificate_settings_are_documented():
    """ADR-281's storage settings were absent, and their absence is quiet: an
    empty bucket name disables uploads with a 503 rather than an error, so a
    rebuilt .env silently turns the feature off."""
    template = _template_keys()
    assert "ore_certificate_bucket" in template
    assert "ore_certificate_kms_key_id" in template
