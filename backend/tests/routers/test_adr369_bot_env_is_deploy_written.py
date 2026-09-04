"""The bot's M2M credentials survive a deploy (ADR-369).

The ADR-363 cutover was done by editing bot/.env on the box. Every deploy
rewrites that file from scratch:

    open('/home/ubuntu/AsheFlow/bot/.env', 'w').write(...)

'w', not 'a'. So the next push silently reverted the bot to the password path,
and the only symptom was one log line changing from "Bot M2M token acquired" to
"Bot Cognito token refreshed" in a container nobody tails.

A silent reversion to a WORKING fallback is the hardest kind to notice: nothing
errored, the bot ran, and the API calls succeeded.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CI = ROOT / ".github" / "workflows" / "ci.yml"
BOT_CONFIG = ROOT / "bot" / "config.py"

# The workflow encodes parameter names as chr() sums so the file carries no
# literal secret names. Decode before asserting, or the test pins the encoding
# rather than the behaviour.
_CHR = re.compile(r"chr\((\d+)\)")


def _keep_set() -> set[str]:
    s = CI.read_text(errors="ignore")
    i = s.index("keep={")
    body = s[i + 6: s.index("}", i)]
    return {
        _CHR.sub(lambda m: chr(int(m.group(1))), chunk).replace("+", "")
        for chunk in body.split(",")
    }


class TestTheDeployWritesTheM2MCredentials:
    @pytest.mark.parametrize("name", [
        "COGNITO_M2M_CLIENT_ID",
        "COGNITO_M2M_CLIENT_SECRET",
        "COGNITO_OAUTH_DOMAIN",
    ])
    def test_it_is_in_the_keep_set(self, name):
        assert name in _keep_set(), (
            f"{name} is not written by the deploy, so a hand-edited bot/.env is "
            "reverted on the next push and the bot silently falls back to the "
            "password path"
        )

    def test_the_existing_bot_secrets_are_still_written(self):
        """A careless edit to the keep set could drop these, which WOULD be
        loud -- but only after a deploy."""
        keep = _keep_set()
        for name in ("DISCORD_BOT_TOKEN", "BOT_USERNAME", "BOT_PASSWORD", "INTERNAL_SECRET"):
            assert name in keep, f"{name} would stop being written to bot/.env"


class TestAMissingParameterFallsBack:
    """ADR-369 D2 -- prod has no M2M parameters yet, so the deploy must succeed
    and leave the bot on the password path rather than half-configured."""

    def test_the_bot_requires_both_values_before_using_m2m(self):
        src = BOT_CONFIG.read_text(errors="ignore")
        for field in ("cognito_m2m_client_id", "cognito_m2m_client_secret", "cognito_oauth_domain"):
            assert f"{field}: str | None = None" in src, (
                f"{field} must be optional, or an environment without it fails "
                "to start instead of falling back"
            )

    def test_the_client_prefers_m2m_only_when_both_are_set(self):
        client = (ROOT / "bot" / "services" / "api_client.py").read_text(errors="ignore")
        assert "if settings.cognito_m2m_client_id and settings.cognito_m2m_client_secret:" in client, (
            "a half-configured environment must fall back, not attempt M2M with "
            "a missing secret"
        )
