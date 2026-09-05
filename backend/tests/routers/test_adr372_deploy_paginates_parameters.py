"""The deploy fetches every parameter, not the first page (ADR-372).

`get_parameters_by_path` returns 10 per call. The deploy used a single call and
took `[Parameters]` off it, so with 15 parameters everything fit and nobody
noticed. ADR-369 added three more, pushing the total to 18 -- and
DISCORD_BOT_TOKEN and COGNITO_M2M_CLIENT_ID landed on page 2.

The bot then crash-looped:

    ValidationError: 1 validation error for Settings
    discord_bot_token  Field required

An off-by-a-page bug that is invisible until the collection grows past the
default page size, and whose blast radius is "whichever secrets happened to sort
last".
"""
import re
from pathlib import Path

CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
_CHR = re.compile(r"chr\((\d+)\)")


def _decoded() -> str:
    """The workflow encodes names as chr() sums so it carries no literal secret
    names; decode before asserting or the test pins the encoding."""
    return _CHR.sub(lambda m: chr(int(m.group(1))), CI.read_text(errors="ignore")).replace("+", "")


class TestTheFetchIsPaginated:
    def test_it_uses_a_paginator(self):
        src = _decoded()
        assert "get_paginator(get_parameters_by_path)" in src, (
            "a single get_parameters_by_path call returns only the first 10 "
            "parameters; secrets beyond that are silently dropped from bot/.env"
        )

    def test_no_bare_single_call_remains(self):
        src = _decoded()
        assert "ps=c.get_parameters_by_path(" not in src, (
            "the un-paginated call is back"
        )

    def test_every_kept_name_is_still_requested(self):
        """Pagination is worthless if the keep set lost an entry along the way."""
        src = _decoded()
        i = src.index("keep={")
        body = src[i + 6: src.index("}", i)]
        for name in (
            "DISCORD_BOT_TOKEN", "BOT_USERNAME", "BOT_PASSWORD", "INTERNAL_SECRET",
            "COGNITO_M2M_CLIENT_ID", "COGNITO_M2M_CLIENT_SECRET", "COGNITO_OAUTH_DOMAIN",
        ):
            assert name in body, f"{name} would not be written to bot/.env"
